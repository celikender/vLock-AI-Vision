"""RTSP IP camera: one reader thread keeps only the newest decoded frame; JPEG is encoded on request.

The interface matches camera.Camera (start, stop, snapshot, status, size), so monitoring,
previews and SAM use an RTSP camera exactly like the Pi camera.
"""
import ipaddress
import os
import re
import threading
import time
from urllib.parse import quote, urlsplit

# Quiet decoder logs before OpenCV loads: FFmpeg messages can include the stream address.
os.environ.setdefault('OPENCV_LOG_LEVEL', 'ERROR')
os.environ.setdefault('OPENCV_FFMPEG_LOGLEVEL', '-8')
# TCP avoids the lost-packet artefacts UDP RTSP shows over Wi-Fi.
os.environ.setdefault('OPENCV_FFMPEG_CAPTURE_OPTIONS', 'rtsp_transport;tcp')

MAX_SIZE = (1280, 960)
FRESH_SECONDS = 2
PRIVATE = [ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]


def rtsp_address(value):
    """Normalise rtsp://<private IPv4>[:port]/path[?query]; credentials go in separate fields."""
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise ValueError('Enter the RTSP address, for example rtsp://192.168.1.64:554/stream1.')
    value = value.strip()
    parts = urlsplit(value if '://' in value else 'rtsp://' + value)
    if parts.scheme != 'rtsp':
        raise ValueError('Use an rtsp:// camera address.')
    if parts.username is not None or parts.password is not None or '@' in parts.netloc:
        raise ValueError('Enter the camera username and password in their own fields, not in the address.')
    if parts.fragment or not re.fullmatch(r'[A-Za-z0-9/_.~%=&;:+,-]*', parts.path + parts.query):
        raise ValueError('The RTSP path or query contains unsupported characters.')
    try:
        host = ipaddress.IPv4Address(parts.hostname)
        port = 554 if parts.port is None else parts.port
    except (ValueError, TypeError):
        raise ValueError('Use a private LAN camera IPv4 address and valid port.') from None
    if not any(host in network for network in PRIVATE) or not 1 <= port <= 65535:
        raise ValueError('Use a private LAN camera IPv4 address and valid port.')
    return f'rtsp://{host}:{port}{parts.path or "/"}' + (f'?{parts.query}' if parts.query else '')


def with_login(url, username='', password=''):
    if not username:
        return url
    return url.replace('rtsp://', f'rtsp://{quote(username, safe="")}:{quote(password, safe="")}@', 1)


def open_stream(url):
    import cv2
    capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG,
                               [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


class RtspCamera:
    def __init__(self, url, username='', password='', opener=open_stream):
        self.url = rtsp_address(url)
        self.username, self.password = username or '', password or ''
        self.opener = opener
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.frame = None
        self.sequence = 0
        self.jpeg = None
        self.jpeg_sequence = None
        self.size = None
        self.captured_at = None
        self.error = None
        self.frames_received = 0
        self.failures = 0
        self.started_at = None
        self.first_frame = threading.Event()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.started_at = time.monotonic()
        self.thread = threading.Thread(target=self._read, name='rtsp-latest-frame', daemon=True)
        self.thread.start()

    def stop(self):
        with self.lock:
            # Set under the lock: the reader checks it before storing, so no frame lands after stop.
            self.stop_event.set()
            self.frame = self.jpeg = None
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=6)

    def wait_first(self, seconds=6):
        """Block until the first frame or a clear error; connect() reports it to the operator."""
        if not self.first_frame.wait(seconds):
            raise OSError(self.error or 'The RTSP camera sent no frame in time. Check the address, login and stream path.')

    def _fail(self, message):
        with self.lock:
            self.frame = self.jpeg = None
            self.failures += 1
            self.error = message

    def _read(self):
        backoff = 1
        while not self.stop_event.is_set():
            capture = None
            try:
                capture = self.opener(with_login(self.url, self.username, self.password))
                if not capture.isOpened():
                    # Never include the address in messages: it can carry the login.
                    raise OSError('Cannot open the RTSP stream. Check the address, port, path and login.')
                while not self.stop_event.is_set():
                    ok, frame = capture.read()
                    if not ok or frame is None or getattr(frame, 'ndim', 0) != 3:
                        raise OSError('The RTSP stream stopped sending frames.')
                    now = time.monotonic()
                    with self.lock:
                        if self.stop_event.is_set():
                            break
                        self.frame, self.captured_at = frame, now
                        self.sequence += 1
                        self.frames_received += 1
                        self.error = None
                    self.first_frame.set()
                    backoff = 1
            except Exception as error:
                self._fail(str(error) if isinstance(error, OSError) else 'The RTSP stream failed. Reconnecting.')
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, 8)
            finally:
                if capture is not None:
                    try:
                        capture.release()
                    except Exception:
                        pass

    def snapshot(self):
        if self.stop_event.is_set():
            raise OSError('Camera disconnected.')
        with self.lock:
            if not self.status()['connected']:
                raise OSError(self.error or 'No fresh camera frame is available.')
            frame, sequence, captured_at = self.frame, self.sequence, self.captured_at
            cached = self.jpeg if self.jpeg_sequence == sequence else None
        if cached is None:
            cached, size = self.encode(frame)
            with self.lock:
                if self.sequence == sequence:
                    self.jpeg, self.jpeg_sequence, self.size = cached, sequence, size
        return cached, {'X-Frame-Sequence': str(sequence),
                        'X-Frame-Age-Ms': str(round((time.monotonic() - captured_at) * 1000))}

    @staticmethod
    def encode(frame):
        """Fit the frame inside MAX_SIZE (SAM time and the 2 MP limit), then encode one JPEG."""
        import cv2
        height, width = frame.shape[:2]
        scale = min(1., MAX_SIZE[0] / width, MAX_SIZE[1] / height)
        if scale < 1:
            frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                               interpolation=cv2.INTER_AREA)
        ok, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise OSError('The RTSP frame could not be encoded.')
        return buffer.tobytes(), [frame.shape[1], frame.shape[0]]

    def status(self):
        with self.lock:
            now = time.monotonic()
            fresh = self.frame is not None and self.captured_at is not None and now - self.captured_at <= FRESH_SECONDS
            if fresh and self.size is None:
                height, width = self.frame.shape[:2]
                scale = min(1., MAX_SIZE[0] / width, MAX_SIZE[1] / height)
                self.size = [max(1, round(width * scale)), max(1, round(height * scale))]
            return dict(connected=fresh, frame_size=self.size, error=self.error,
                        frame_sequence=str(self.sequence) if fresh else None,
                        frame_age_seconds=round(now - self.captured_at, 3) if fresh else None,
                        request_ms=None,
                        transport_fps=round(self.frames_received / max(.1, now - self.started_at), 1) if self.started_at else None,
                        failures=self.failures, streaming=bool(self.thread and self.thread.is_alive()))
