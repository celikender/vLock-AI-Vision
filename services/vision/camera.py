"""Bounded original-JPEG transport for the tested private-LAN Pi camera."""
import http.client
import ipaddress
import math
import threading
import time
from io import BytesIO
from urllib.parse import urlsplit

from PIL import Image


def address(value):
    if not isinstance(value, str) or len(value) > 300:
        raise ValueError('Enter a private LAN camera IPv4 address and port.')
    parts = urlsplit(value.strip() if '://' in value else 'http://' + value.strip())
    if (parts.scheme != 'http' or parts.username is not None or parts.password is not None
            or parts.path not in ('', '/', '/snapshot.jpg') or parts.query or parts.fragment):
        raise ValueError('Use the Pi HTTP camera address without credentials or query parameters.')
    try:
        host = ipaddress.IPv4Address(parts.hostname)
        port = 8080 if parts.port is None else parts.port
        if not any(host in ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')) or not 1 <= port <= 65535:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Use a private LAN camera IPv4 address and valid port.') from None
    return str(host), port


def fetch_jpeg(value):
    host, port = address(value)
    connection = http.client.HTTPConnection(host, port, timeout=2)
    try:
        connection.request('GET', '/snapshot.jpg', headers={'Connection':'close'})
        response = connection.getresponse()
        if response.status != 200 or response.getheader('Content-Type','').split(';')[0] != 'image/jpeg':
            raise OSError('Camera did not return a JPEG frame.')
        jpeg = response.read(2 * 1024 * 1024 + 1)
        if len(jpeg) > 2 * 1024 * 1024 or not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
            raise OSError('Camera returned an invalid or oversized JPEG.')
        headers = {k:response.getheader(k,'') for k in ('X-Frame-Sequence','X-Frame-Age-Ms')}
        return jpeg, headers
    finally:
        connection.close()


class Camera:
    def __init__(self, url, fetch=fetch_jpeg):
        address(url)
        self.url, self.fetch = url, fetch
        self.lock = threading.RLock()
        self.jpeg = None
        self.headers = {}
        self.size = None
        self.captured_at = None
        self.received_at = None
        self.error = None
        self.stop_event = threading.Event()
        self.thread = None
        self.request_ms = None
        self.frames_received = 0
        self.failures = 0
        self.started_at = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.started_at = time.monotonic()
        self.thread = threading.Thread(target=self._poll, name='camera-latest-frame', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        with self.lock:self.jpeg=None
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2.5)

    def _poll(self):
        while not self.stop_event.is_set():
            began = time.monotonic()
            try:
                self._capture()
                delay = max(0, .05-(time.monotonic()-began))
            except OSError:
                delay = .25
            self.stop_event.wait(delay)

    def snapshot(self):
        if self.stop_event.is_set():raise OSError('Camera disconnected.')
        if self.thread is not None:
            with self.lock:
                if not self.status()['connected']:
                    raise OSError(self.error or 'No fresh camera frame is available.')
                headers = dict(self.headers)
                headers['X-Frame-Age-Ms'] = str(round((time.monotonic()-self.captured_at)*1000))
                return self.jpeg, headers
        return self._capture()

    def _capture(self):
        began = time.monotonic()
        try:
            jpeg, headers = self.fetch(self.url)
            sequence = headers.get('X-Frame-Sequence')
            age = float(headers.get('X-Frame-Age-Ms','nan'))
            if not isinstance(sequence,str) or not sequence.isdigit() or not math.isfinite(age) or not 0 <= age <= 2000:
                raise OSError('Camera freshness metadata is missing or stale.')
            with Image.open(BytesIO(jpeg)) as image:
                size = list(image.size)
                if image.format != 'JPEG' or max(size) > 4096 or size[0]*size[1] > 2_000_000:
                    raise OSError('Use a JPEG camera frame up to two megapixels.')
                image.verify()
            now = time.monotonic()
            with self.lock:
                if self.stop_event.is_set():raise OSError('Camera disconnected.')
                if self.headers.get('X-Frame-Sequence') == sequence and self.received_at is not None:
                    if now-self.received_at > 2:
                        raise OSError('The camera frame sequence stopped advancing.')
                else:
                    self.received_at = now
                    self.frames_received += 1
                self.jpeg, self.headers, self.size = jpeg, dict(headers), size
                self.captured_at = now-age/1000
                self.request_ms = round((now-began)*1000,1)
                self.error = None
                return jpeg, dict(headers)
        except Exception:
            with self.lock:
                self.jpeg = None
                self.failures += 1
                self.error = 'Camera unavailable or stale. Check its address and service.'
            raise OSError(self.error) from None

    def status(self):
        with self.lock:
            fresh = (self.jpeg is not None and self.captured_at is not None and
                     time.monotonic()-self.captured_at <= 2 and self.received_at is not None and
                     time.monotonic()-self.received_at <= 2)
            return dict(connected=fresh, frame_size=self.size, error=self.error,
                        frame_sequence=self.headers.get('X-Frame-Sequence'),
                        frame_age_seconds=round(time.monotonic()-self.captured_at,3) if fresh else None,
                        request_ms=self.request_ms,transport_fps=round(self.frames_received/max(.1,time.monotonic()-self.started_at),1) if self.started_at else None,
                        failures=self.failures,streaming=bool(self.thread and self.thread.is_alive()))
