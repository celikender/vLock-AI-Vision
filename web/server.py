"""Local PC camera UI and bounded LAN snapshot relay. No extra dependencies."""
import http.client
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

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
