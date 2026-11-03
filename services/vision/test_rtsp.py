"""RTSP camera checks with an injected stream; no network camera or FFmpeg connection is used."""
import threading
import time
import unittest
from io import BytesIO

import numpy as np
from PIL import Image

from services.vision.rtsp import RtspCamera, rtsp_address, with_login


class FakeStream:
    def __init__(self, size=(1080, 1920), frames=None, opened=True):
        self.size, self.frames, self.opened = size, frames, opened
        self.released = False
        self.count = 0

    def isOpened(self):
        return self.opened

    def set(self, *args):
        return True

    def read(self):
        time.sleep(.01)
        self.count += 1
        if self.frames is not None and self.count > self.frames:
            return False, None
        return True, np.full(self.size + (3,), self.count % 255, dtype=np.uint8)

    def release(self):
        self.released = True


def until(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(.02)
    raise AssertionError('Expected RTSP camera state was not reached.')


class AddressTests(unittest.TestCase):
    def test_private_rtsp_addresses_without_credentials(self):
        self.assertEqual(rtsp_address('rtsp://192.168.1.64/stream2'), 'rtsp://192.168.1.64:554/stream2')
        self.assertEqual(rtsp_address('192.168.1.64:8554/Streaming/Channels/102'),
                         'rtsp://192.168.1.64:8554/Streaming/Channels/102')
        self.assertEqual(rtsp_address('rtsp://10.0.0.5:554/cam/realmonitor?channel=1&subtype=1'),
                         'rtsp://10.0.0.5:554/cam/realmonitor?channel=1&subtype=1')
        for bad in ['rtsp://admin:secret@192.168.1.64/stream', 'http://192.168.1.64/stream', 'rtsp://8.8.8.8/stream',
                    'rtsp://camera.local/stream', 'rtsp://192.168.1.64:99999/stream', 'rtsp://192.168.1.64/a b', '']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                rtsp_address(bad)

    def test_login_is_quoted_into_the_stream_url_only(self):
        self.assertEqual(with_login('rtsp://192.168.1.64:554/s', 'admin', 'p@ss:w/rd'),
                         'rtsp://admin:p%40ss%3Aw%2Frd@192.168.1.64:554/s')
        self.assertEqual(with_login('rtsp://192.168.1.64:554/s'), 'rtsp://192.168.1.64:554/s')


class CameraTests(unittest.TestCase):
    def test_latest_frame_is_scaled_encoded_once_and_fresh(self):
        opened = []
        camera = RtspCamera('rtsp://192.168.1.64/stream', 'admin', 'secret-pass',
                            opener=lambda url: opened.append(url) or FakeStream())
        camera.start()
        try:
            camera.wait_first(2)
            self.assertEqual(opened, ['rtsp://admin:secret-pass@192.168.1.64:554/stream'])
            jpeg, headers = camera.snapshot()
            with Image.open(BytesIO(jpeg)) as image:
                self.assertEqual((image.format, image.size), ('JPEG', (1280, 720)))
            self.assertEqual(camera.status()['frame_size'], [1280, 720])
            self.assertTrue(headers['X-Frame-Sequence'].isdigit())
            self.assertLessEqual(int(headers['X-Frame-Age-Ms']), 2000)
            until(lambda: camera.snapshot()[1]['X-Frame-Sequence'] != headers['X-Frame-Sequence'])
            status = camera.status()
            self.assertTrue(status['connected'] and status['streaming'])
        finally:
            camera.stop()
        self.assertFalse(camera.status()['connected'])
        with self.assertRaises(OSError):
            camera.snapshot()

    def test_lost_stream_reconnects_and_messages_never_show_the_login(self):
        streams = []

        def opener(url):
            streams.append(FakeStream(size=(480, 640), frames=5))
            return streams[-1]
        camera = RtspCamera('rtsp://192.168.1.64/stream', 'admin', 'secret-pass', opener=opener)
        camera.start()
        try:
            camera.wait_first(2)
            until(lambda: camera.status()['failures'] >= 1)
            self.assertIn('stopped sending frames', camera.status()['error'])
            until(lambda: len(streams) >= 2, 4)
            self.assertTrue(streams[0].released)
            for text in (camera.status()['error'] or '',):
                self.assertNotIn('secret-pass', text)
                self.assertNotIn('192.168.1.64', text)
        finally:
            camera.stop()

    def test_unopened_stream_reports_a_clear_error(self):
        camera = RtspCamera('rtsp://192.168.1.64/stream', 'admin', 'wrong', opener=lambda url: FakeStream(opened=False))
        camera.start()
        try:
            with self.assertRaises(OSError) as caught:
                camera.wait_first(1.5)
            self.assertIn('Cannot open the RTSP stream', str(caught.exception))
            self.assertNotIn('wrong', str(caught.exception))
            self.assertFalse(camera.status()['connected'])
        finally:
            camera.stop()

    def test_real_decoder_reads_a_local_video_file(self):
        """The real OpenCV path decodes frames; a local file stands in for the RTSP server."""
        import os
        import tempfile
        import cv2
        from services.vision.rtsp import open_stream
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'clip.avi')
            writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'MJPG'), 10, (640, 480))
            for index in range(30):
                writer.write(np.full((480, 640, 3), index * 8, dtype=np.uint8))
            writer.release()
            capture = open_stream(path)
            try:
                self.assertTrue(capture.isOpened())
                ok, frame = capture.read()
                self.assertTrue(ok)
                self.assertEqual(frame.shape, (480, 640, 3))
                jpeg, size = RtspCamera.encode(frame)
                self.assertEqual(size, [640, 480])
                self.assertTrue(jpeg.startswith(b'\xff\xd8'))
            finally:
                capture.release()


if __name__ == '__main__':
    unittest.main()
