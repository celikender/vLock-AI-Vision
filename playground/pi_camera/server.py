"""Pi USB MJPEG playground. Python standard library + system ffmpeg."""
import argparse
import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def jpeg_frames(pipe):
    buffer = bytearray()
    while chunk := pipe.read(16384):
        buffer.extend(chunk)
        while True:
            start = buffer.find(b'\xff\xd8')
            if start < 0:
                buffer[:] = buffer[-1:]
                break
            end = buffer.find(b'\xff\xd9', start + 2)
            if end < 0:
                del buffer[:start]
                if len(buffer) > 8 * 1024 * 1024:
                    raise ValueError('Oversized camera frame')
                break
            yield bytes(buffer[start:end + 2])
            del buffer[:end + 2]


class Camera:
    def __init__(self, args):
        self.args = args
        self.lock = threading.Lock()
        self.frame = None
        self.timestamp = 0
        self.sequence = 0
        self.stop = threading.Event()
        self.process = None

    def latest(self):
        with self.lock:
            age = time.monotonic() - self.timestamp
            return self.frame if age < 2 else None, age, self.sequence

    def run(self):
        while not self.stop.is_set():
            command = ['ffmpeg', '-hide_banner', '-loglevel', 'warning',
                       '-f', 'v4l2', '-input_format', 'mjpeg', '-video_size', self.args.size,
                       '-framerate', str(self.args.fps), '-i', self.args.device,
                       '-an', '-c:v', 'copy', '-f', 'image2pipe', '-flush_packets', '1', 'pipe:1']
            try:
                self.process = subprocess.Popen(command, stdout=subprocess.PIPE, bufsize=0)
                for frame in jpeg_frames(self.process.stdout):
                    if self.stop.is_set():
                        break
                    with self.lock:
                        self.frame = frame
                        self.timestamp = time.monotonic()
                        self.sequence += 1
            except (OSError, ValueError) as error:
                print(error, flush=True)
            finally:
                if self.process:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait()
                    self.process.stdout.close()
                with self.lock:
                    self.frame = None
            self.stop.wait(2)


def handler(camera):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self):
            self.connection.settimeout(5)
            path = self.path.split('?')[0]
            frame, age, sequence = camera.latest()
            headers = {}
            if path == '/':
                body = Path(__file__).with_name('index.html').read_bytes()
                code, mime = 200, 'text/html; charset=utf-8'
            elif path == '/health':
                code, mime = (200 if frame else 503), 'application/json'
                body = json.dumps({'ready': frame is not None, 'sequence': sequence,
                                   'frame_age_ms': round(age * 1000) if frame else None}).encode()
            elif path == '/snapshot.jpg':
                code, mime, body = (200, 'image/jpeg', frame) if frame else (503, 'text/plain', b'Camera unavailable; reconnect USB or check service logs.')
                headers = {'X-Frame-Sequence': str(sequence), 'X-Frame-Age-Ms': str(round(age * 1000))}
            else:
                code, mime, body = 404, 'text/plain', b'Not found'
            try:
                self.send_response(code)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass

        def log_message(self, *args):
            pass
    return Handler


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', default='/dev/video0')
    parser.add_argument('--size', default='640x480')
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    camera = Camera(args)
    worker = threading.Thread(target=camera.run, daemon=True)
    worker.start()
    server = ThreadingHTTPServer(('0.0.0.0', args.port), handler(camera))
    server.daemon_threads = True
    print(f'Camera playground listening on port {args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        camera.stop.set()
        if camera.process and camera.process.poll() is None:
            camera.process.terminate()
        server.server_close()
        worker.join(timeout=5)
