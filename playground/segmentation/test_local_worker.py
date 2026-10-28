import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from io import BytesIO
from PIL import Image
import local_worker

class LocalWorkerTests(unittest.TestCase):
    def setUp(self):
        self.client=local_worker.app.test_client()
    def test_browser_origin_rejected(self):
        response=self.client.get('/health',base_url='http://localhost:5052',headers={'Origin':'https://example.com'})
        self.assertEqual(response.status_code,403)
    def test_missing_weights(self):
        fake=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True))
        buffer=BytesIO();Image.new('RGB',(10,10),'white').save(buffer,'JPEG')
        with patch.dict(sys.modules,{'torch':fake}), patch('local_worker.checkpoint',return_value=None):
            response=self.client.post('/segment?prompt=monitor',data=buffer.getvalue(),base_url='http://localhost:5052')
        self.assertEqual(response.status_code,503)
        self.assertIn('weights missing',response.json['error'])
    def test_status_without_weights(self):
        fake=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True))
        with patch.dict(sys.modules,{'torch':fake}), patch('local_worker.checkpoint',return_value=None):
            response=self.client.get('/health',base_url='http://localhost:5052')
        self.assertFalse(response.json['ready'])
        self.assertTrue(response.json['cuda'])