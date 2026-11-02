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

    def snapshot(self):
        with self.lock:
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
                if self.headers.get('X-Frame-Sequence') == sequence and self.received_at is not None:
                    if now - self.received_at > 2:
                        raise OSError('The camera frame sequence stopped advancing.')
                else:
                    self.received_at = now
                self.jpeg, self.headers, self.size = jpeg, dict(headers), size
                self.captured_at = now - age/1000
                self.error = None
                return jpeg, dict(headers)
            except Exception:
                self.jpeg = None
                self.error = 'Camera unavailable or stale. Check its address and service.'
                raise OSError(self.error) from None

    def status(self):
        with self.lock:
            fresh = (self.jpeg is not None and self.captured_at is not None and
                     time.monotonic()-self.captured_at <= 2 and self.received_at is not None and
                     time.monotonic()-self.received_at <= 2)
            return dict(connected=fresh, frame_size=self.size, error=self.error,
                        frame_sequence=self.headers.get('X-Frame-Sequence'),
                        frame_age_seconds=round(time.monotonic()-self.captured_at,3) if fresh else None)
