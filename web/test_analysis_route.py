import base64
import http.client
import json
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4
from http.server import ThreadingHTTPServer
import server

class AnalysisRouteTests(unittest.TestCase):
    def setUp(self):
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join()
    def post(self,payload,origin='http://localhost:5051'):
        connection=http.client.HTTPConnection('127.0.0.1',self.http.server_port)
        connection.request('POST','/api/analyze',json.dumps(payload),headers={'Host':'localhost:5051','Origin':origin,'Content-Type':'application/json'})
        response=connection.getresponse();code=response.status;body=json.loads(response.read());connection.close()
        return code,body
    def test_roundtrip_identity(self):
        capture_id=str(uuid4())
        with patch('server.annotate_photo',return_value={'answer':'ok','boxes':[]}) as provider:
            code,body=self.post({'capture_id':capture_id,'image':base64.b64encode(b'image').decode(),'prompt':'eyes'})
            self.assertEqual(code,200);self.assertEqual(body['capture_id'],capture_id)
            provider.assert_called_once_with(b'image','eyes')
    def test_bad_origin_never_calls_provider(self):
        with patch('server.annotate_photo') as provider:
            self.assertEqual(self.post({},'https://example.com')[0],403)
            provider.assert_not_called()
    def test_bad_request(self):
        self.assertEqual(self.post({'capture_id':'bad'})[0],400)
    def test_busy_model(self):
        server.MODEL_LOCK.acquire()
        try:
            self.assertEqual(self.post({'capture_id':str(uuid4()),'image':'aW1hZ2U='})[0],409)
        finally:
            server.MODEL_LOCK.release()
class SegmentationRouteTests(AnalysisRouteTests):
    def test_segment_backend_and_capture(self):
        capture_id=str(uuid4())
        connection=http.client.HTTPConnection('127.0.0.1',self.http.server_port)
        with patch('server.segment_photo',return_value={'backend':'local','count':1}) as segmenter:
            payload={'capture_id':capture_id,'image':'aW1hZ2U=','prompt':'monitor','backend':'local'}
            connection.request('POST','/api/segment',json.dumps(payload),headers={'Host':'localhost:5051','Origin':'http://localhost:5051','Content-Type':'application/json'})
            response=connection.getresponse();body=json.loads(response.read())
            self.assertEqual(response.status,200)
            self.assertEqual(body['capture_id'],capture_id)
            segmenter.assert_called_once_with(b'image','monitor','local')
        connection.close()
