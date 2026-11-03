import io
import threading
import time
import unittest
import urllib.request
import urllib.error
from types import SimpleNamespace
from http.server import ThreadingHTTPServer
from server import Camera, handler, jpeg_frames


class Tests(unittest.TestCase):
    def test_split_frames(self):
        class Chunks:
            def __init__(self):
                self.parts = iter([b'junk\xff', b'\xd8one\xff', b'\xd9\xff\xd8two\xff\xd9', b''])
            def read(self, _):
                return next(self.parts)
        self.assertEqual(list(jpeg_frames(Chunks())), [b'\xff\xd8one\xff\xd9', b'\xff\xd8two\xff\xd9'])

    def test_snapshot_and_stale_frame(self):
        camera = Camera(SimpleNamespace())
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(camera))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + '/snapshot.jpg')
            self.assertEqual(error.exception.code, 503)
            error.exception.close()
            with camera.lock:
                camera.frame = b'\xff\xd8test\xff\xd9'
                camera.timestamp = time.monotonic()
                camera.sequence = 7
            with urllib.request.urlopen(base + '/snapshot.jpg') as response:
                self.assertEqual(response.read(), camera.frame)
                self.assertEqual(response.headers['X-Frame-Sequence'], '7')
            camera.timestamp -= 3
            self.assertIsNone(camera.latest()[0])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
