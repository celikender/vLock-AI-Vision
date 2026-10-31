"""Loopback-only vLock bridge UI/API with optional MQTT and OPC UA adapters."""
import argparse
import json
import sqlite3
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from store import BridgeError, Store, encode, identifier
from transports import Integrations

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE.parent / 'data' / 'vlock_bridge' / 'bridge.sqlite3'


def handler(store, integrations=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, code, value, mime='application/json; charset=utf-8'):
            body = value if isinstance(value, bytes) else encode(value).encode()
            self.send_response(code)
            for name, header in {
                'Content-Type': mime, 'Content-Length': str(len(body)), 'Cache-Control': 'no-store',
                'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
                'Content-Security-Policy': "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }.items():
                self.send_header(name, header)
            try:
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionError, TimeoutError):
                # A closing browser is a lost reader, not a storage failure.
                pass

        def local_request(self):
            self.connection.settimeout(5)
            host = self.headers.get('Host')
            allowed = (f'localhost:{self.server.server_port}', f'127.0.0.1:{self.server.server_port}')
            scheme = 'https' if isinstance(self.connection, ssl.SSLSocket) else 'http'
            if host not in allowed or self.headers.get('Origin') not in (None, scheme + '://' + host):
                raise BridgeError('Use the local bridge address.', 403)
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise BridgeError('Cross-site requests are not allowed.', 403)

        def do_GET(self):
            try:
                self.local_request()
                url = urlsplit(self.path)
                static = {'/': ('index.html', 'text/html; charset=utf-8'),
                          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                          '/heartbeat.js': ('heartbeat.js', 'text/javascript; charset=utf-8'),
                          '/style.css': ('style.css', 'text/css; charset=utf-8')}
                if url.path in static:
                    name, mime = static[url.path]
                    return self.reply(200, (HERE / name).read_bytes(), mime)
                if url.path == '/api/v1/health':
                    state = store.snapshot()
                    return self.reply(200, dict(schema_version=1, status='ok',
                        session_id=state['session_id'], heartbeat=state['heartbeat'], revision=state['revision'],
                        **{key: state[key] for key in ('online', 'heartbeat_counter', 'heartbeat_pulse',
                            'heartbeat_interval_seconds', 'offline_after_seconds')}))
                if url.path == '/api/v1/integrations':
                    if integrations is None:
                        raise BridgeError('Integration manager is not running.', 503)
                    return self.reply(200, integrations.status())
                if url.path == '/api/v1/assets':
                    return self.reply(200, store.snapshot())
                if url.path.startswith('/api/v1/assets/'):
                    asset_id = identifier(url.path.removeprefix('/api/v1/assets/'), 'asset_id')
                    state = store.snapshot()
                    asset = next((a for a in state['assets'] if a['asset_id'] == asset_id), None)
                    if asset is None:
                        raise BridgeError('Asset has no observations yet.', 404)
                    return self.reply(200, {k: v for k, v in state.items() if k != 'assets'} | asset)
                if url.path == '/api/v1/events':
                    params = parse_qs(url.query)
                    try:
                        after = int(params['after'][0]) if 'after' in params else None
                        limit = int(params.get('limit', ['50'])[0])
                        if (after is not None and not 0 <= after <= 9223372036854775807) or not 1 <= limit <= 200:
                            raise ValueError()
                    except ValueError:
                        raise BridgeError('Use a nonnegative 64-bit after revision and limit from 1 to 200.') from None
                    events = store.events(after, limit)
                    history = store.history_info()
                    return self.reply(200, dict(schema_version=1, events=events,
                        next_after=events[-1]['revision'] if events else (after or 0), **history,
                        cursor_expired=after is not None and history['oldest_revision'] is not None and after + 1 < history['oldest_revision']))
                raise BridgeError('Not found.', 404)
            except BridgeError as error:
                self.reply(error.status, {'error': str(error)})
            except (sqlite3.Error, OSError):
                self.reply(503, {'error': 'Bridge storage unavailable. Check the local server.'})

        def do_POST(self):
            try:
                self.local_request()
                if self.path not in ('/api/v1/observations', '/api/v1/integrations'):
                    raise BridgeError('Not found.', 404)
                if self.headers.get('Transfer-Encoding'):
                    raise BridgeError('Send Content-Length; chunked uploads are not supported.')
                if self.headers.get_content_type() != 'application/json':
                    raise BridgeError('Use Content-Type: application/json.', 415)
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    raise BridgeError('Invalid Content-Length.') from None
                if not 0 < length <= 65536:
                    raise BridgeError('Send a JSON body from 1 byte to 64 KiB.', 413)
                try:
                    data = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeError, RecursionError):
                    raise BridgeError('Invalid JSON.') from None
                if self.path == '/api/v1/integrations':
                    if integrations is None:
                        raise BridgeError('Integration manager is not running.', 503)
                    return self.reply(200, integrations.apply(data))
                result = store.submit(data)
                self.reply(200 if result['duplicate'] else 201, dict(schema_version=1, **result))
            except BridgeError as error:
                self.reply(error.status, {'error': str(error)})
            except (sqlite3.Error, OSError):
                self.reply(503, {'error': 'Observation was not confirmed. Check storage before retrying with the same observation_id.'})
    return Handler


def make_server(store, port=5055, certfile=None, keyfile=None, integrations=None):
    if bool(certfile) != bool(keyfile):
        raise ValueError('Supply both --certfile and --keyfile for HTTPS.')
    context = None
    if certfile:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile, keyfile)
    server = ThreadingHTTPServer(('127.0.0.1', port), handler(store, integrations))
    if context:
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


def main():
    parser = argparse.ArgumentParser(description='Local vLock observation bridge')
    parser.add_argument('--port', type=int, default=5055)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--certfile', type=Path)
    parser.add_argument('--keyfile', type=Path)
    parser.add_argument('--settings', type=Path, help='Local adapter settings JSON; defaults beside the database.')
    parser.add_argument('--history-limit', type=int, default=1000, help='Retain this many events (5-100000; default 1000).')
    parser.add_argument('--heartbeat-seconds', type=int, default=1, help='Heartbeat interval (1-60; default 1).')
    args = parser.parse_args()
    if not 5 <= args.history_limit <= 100000 or not 1 <= args.heartbeat_seconds <= 60:
        parser.error('Use --history-limit 5-100000 and --heartbeat-seconds 1-60.')
    store = Store(args.db, heartbeat_interval_seconds=args.heartbeat_seconds, history_limit=args.history_limit)
    integrations = Integrations(store, args.settings or args.db.parent / 'transports.json')
    try:
        server = make_server(store, args.port, args.certfile, args.keyfile, integrations)
    except (OSError, ValueError):
        integrations.close()
        store.close()
        parser.exit(1, 'Cannot start bridge. Check port, database and certificate configuration.\n')
    scheme = 'https' if args.certfile else 'http'
    print(f'vLock Bridge: {scheme}://localhost:{server.server_port}', flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        integrations.close()
        store.close()


if __name__ == '__main__':
    main()
