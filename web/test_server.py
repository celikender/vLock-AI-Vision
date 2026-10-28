import unittest
from unittest.mock import patch, MagicMock
from server import camera_address, snapshot


class CameraRelayTests(unittest.TestCase):
    def test_addresses(self):
        self.assertEqual(camera_address('192.168.1.50'), ('192.168.1.50', 8080))
        self.assertEqual(camera_address('10.0.0.2:9000'), ('10.0.0.2', 9000))
        for invalid in ('127.0.0.1', '8.8.8.8', '169.254.169.254', 'example.com',
                        'http://192.168.1.2', '192.168.1.2:99999', '192.168.1.2:0'):
            with self.assertRaises(ValueError):
                camera_address(invalid)

    @patch('server.http.client.HTTPConnection')
    def test_relay_preserves_bytes(self, factory):
        response = factory.return_value.getresponse.return_value
        response.status = 200
        response.getheader.side_effect = lambda name, default='': {'Content-Type':'image/jpeg', 'X-Frame-Sequence':'42','X-Frame-Age-Ms':'3'}.get(name, default)
        response.read.return_value = b'\xff\xd8original\xff\xd9'
        body, headers = snapshot('192.168.1.50')
        self.assertEqual(body, response.read.return_value)
        self.assertEqual(headers['X-Frame-Sequence'], '42')
        factory.return_value.close.assert_called_once()

    @patch('server.http.client.HTTPConnection')
    def test_redirect_not_followed(self, factory):
        factory.return_value.getresponse.return_value.status = 302
        with self.assertRaises(OSError):
            snapshot('192.168.1.50')
        factory.return_value.close.assert_called_once()

    @patch('server.http.client.HTTPConnection')
    def test_bad_jpeg_rejected(self, factory):
        response = factory.return_value.getresponse.return_value
        response.status = 200
        response.getheader.return_value = 'image/jpeg'
        response.read.return_value = b'not a jpeg'
        with self.assertRaises(OSError):
            snapshot('192.168.1.50')


if __name__ == '__main__':
    unittest.main()
