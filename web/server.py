"""Local PC camera UI and bounded LAN snapshot relay. Explicit captured-photo analysis."""
import http.client
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import sys
import json
import base64
import binascii
import threading
from uuid import UUID
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'playground' / 'camera'))
from analysis import AnalysisError
from annotations import annotate_photo
MODEL_LOCK = threading.Lock()
NETWORKS = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def camera_address(value):
    parts = value.strip().split(':')
    if len(parts) > 2:
        raise ValueError('Enter a LAN IPv4 address, optionally followed by :8080.')
    address = ipaddress.IPv4Address(parts[0])
    port = int(parts[1]) if len(parts) == 2 else 8080
    if not any(address in network for network in NETWORKS) or not 1 <= port <= 65535:
        raise ValueError('Use a private LAN IPv4 address and a valid port.')
    return str(address), port


def snapshot(value):
    host, port = camera_address(value)
    connection = http.client.HTTPConnection(host, port, timeout=2)
    try:
        connection.request('GET', '/snapshot.jpg', headers={'Connection': 'close'})
        response = connection.getresponse()
        if response.status != 200 or response.getheader('Content-Type', '').split(';')[0] != 'image/jpeg':
            raise OSError('Pi camera unavailable. Check the USB camera and service.')
        body = response.read(5 * 1024 * 1024 + 1)
        if len(body) > 5 * 1024 * 1024 or not body.startswith(b'\xff\xd8') or not body.endswith(b'\xff\xd9'):
            raise OSError('Pi returned an invalid or oversized JPEG.')
        headers = {name: response.getheader(name, '') for name in ('X-Frame-Sequence', 'X-Frame-Age-Ms')}
        # Forward numeric diagnostics only.
        return body, {k: v for k, v in headers.items() if v.isdigit()}
    finally:
        connection.close()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.connection.settimeout(5)
        headers = {}
        try:
            if self.headers.get('Host') not in ('127.0.0.1:5051', 'localhost:5051'):
                self.reply(403, b'Open localhost:5051.', 'text/plain', {})
                return
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers['Host']:
                self.reply(403, b'Use the local app page.', 'text/plain', {})
                return
            url = urlsplit(self.path)
            if url.path == '/':
                body = Path(__file__).with_name('index.html').read_bytes()
                code, mime = 200, 'text/html; charset=utf-8'
            elif url.path == '/api/snapshot':
                body, headers = snapshot(parse_qs(url.query).get('address', [''])[0])
                code, mime = 200, 'image/jpeg'
            else:
                code, mime, body = 404, 'text/plain', b'Not found'
        except ValueError as error:
            code, mime, body = 400, 'text/plain', str(error).encode()
        except (OSError, http.client.HTTPException):
            code, mime, body = 502, 'text/plain', b'Cannot get a frame. Check Pi address, power, network, and camera service.'
        self.reply(code, body, mime, headers)

    def do_POST(self):
        self.connection.settimeout(10)
        host = self.headers.get('Host')
        if host not in ('localhost:5051', '127.0.0.1:5051') or self.headers.get('Origin') != 'http://' + host:
            self.reply(403, b'{"error":"Use the local app page."}', 'application/json', {})
            return
        if self.path != '/api/analyze':
            self.reply(404, b'{"error":"Not found"}', 'application/json', {})
            return
        acquired = False
        try:
            if self.headers.get('Content-Type') != 'application/json':
                raise AnalysisError('Expected a JSON photo request.', 400)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8 * 1024 * 1024:
                raise AnalysisError('Photo request is too large or empty.', 413)
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError()
            capture_id = str(UUID(payload.get('capture_id', '')))
            question = payload.get('prompt', '')
            if not isinstance(question, str) or len(question) > 2000:
                raise AnalysisError('Keep the prompt under 2,000 characters.', 400)
            jpeg = base64.b64decode(payload.get('image', ''), validate=True)
            if not 0 < len(jpeg) <= 5 * 1024 * 1024:
                raise AnalysisError('Photo must be under 5 MB.', 413)
            acquired = MODEL_LOCK.acquire(blocking=False)
            if not acquired:
                raise AnalysisError('An analysis is already running. Wait and try again.', 409)
            result = annotate_photo(jpeg, question)
            body, code = {'capture_id': capture_id, **result}, 200
        except AnalysisError as error:
            body, code = {'error': str(error)}, error.status
        except (ValueError, TypeError, AttributeError, binascii.Error):
            body, code = {'error': 'Invalid photo request. Capture a new photo.'}, 400
        except Exception:
            body, code = {'error': 'Analysis failed. Check local configuration and try again.'}, 502
        finally:
            if acquired:
                MODEL_LOCK.release()
        self.reply(code, json.dumps(body).encode(), 'application/json', {})
    def reply(self, code, body, mime, headers):
        try:
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 5051), Handler)
    server.daemon_threads = True
    print('Open http://localhost:5051', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
