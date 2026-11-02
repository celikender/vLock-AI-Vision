"""Working application checks with injected camera frames, never live equipment."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.application import Workspace, ApplicationError
from services.vision.camera import Camera, address
from application import make_server
from PIL import Image


def jpeg():
    stream=BytesIO()
    Image.new('RGB',(100,80),'green').save(stream,'JPEG')
    return stream.getvalue()


class CameraTests(unittest.TestCase):
    def test_private_camera_validation(self):
        self.assertEqual(address('192.168.1.50:8080'),('192.168.1.50',8080))
        for value in ['http://8.8.8.8','http://localhost:8080','http://user:secret@192.168.1.50',
                      'https://192.168.1.50','http://192.168.1.50/redirect','http://192.168.1.50?url=other']:
            with self.subTest(value=value),self.assertRaises(ValueError):
                address(value)

    def test_original_jpeg_and_frozen_sequence(self):
        body=jpeg()
        camera=Camera('192.168.1.50',lambda url:(body,{'X-Frame-Sequence':'1','X-Frame-Age-Ms':'0'}))
        with patch('services.vision.camera.time.monotonic',return_value=10):
            self.assertEqual(camera.snapshot()[0],body)
            self.assertTrue(camera.status()['connected'])
        with patch('services.vision.camera.time.monotonic',return_value=13):
            with self.assertRaises(OSError):
                camera.snapshot()
            self.assertFalse(camera.status()['connected'])
            self.assertIsNone(camera.jpeg)

    def test_bad_freshness_never_connects(self):
        for headers in [{},{'X-Frame-Sequence':'1','X-Frame-Age-Ms':'3000'}]:
            camera=Camera('192.168.1.50',lambda url:(jpeg(),headers))
            with self.assertRaises(OSError):
                camera.snapshot()
            self.assertFalse(camera.status()['connected'])


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.frame=jpeg()
        self.sequence=0
        def fetch(url):
            self.sequence+=1
            return self.frame,{'X-Frame-Sequence':str(self.sequence),'X-Frame-Age-Ms':'0'}
        self.workspace=Workspace(self.directory.name,fetch=fetch)

    def tearDown(self):
        self.workspace.close()
        self.directory.cleanup()

    def create(self):
        state=self.workspace.add('Camera zone')['workspace']
        state['zones'][0]['cameraAddress']='192.168.1.50:8080'
        return self.workspace.save(state)['workspace']['zones'][0]['id']

    def test_save_connect_snapshot_and_restart(self):
        zone=self.create()
        state=self.workspace.connect(zone)
        self.assertTrue(state['workspace']['zones'][0]['connected'])
        self.assertEqual(self.workspace.snapshot(zone)[0],self.frame)
        restored=Workspace(self.directory.name)
        try:
            view=restored.status()['workspace']['zones'][0]
            self.assertFalse(view['connected'])
            self.assertFalse(view['localEnabled'])
            self.assertIsNone(view['runtime']['value'])
        finally:
            restored.close()

    def test_revision_conflicts_and_browser_flags_cannot_enable(self):
        stale=self.workspace.status()['workspace']
        zone=self.create()
        with self.assertRaises(ApplicationError) as caught:
            self.workspace.save(stale)
        self.assertEqual(caught.exception.status,409)
        state=self.workspace.status()['workspace']
        state['zones'][0].update(connected=True,localEnabled=True,configured=True,runtime={'value':False,'valid':True})
        view=self.workspace.save(state)['workspace']['zones'][0]
        self.assertFalse(view['connected'])
        self.assertFalse(view['localEnabled'])
        self.assertIsNone(view['runtime']['value'])

    def test_corrupt_configuration_not_overwritten(self):
        self.create()
        path=Path(self.directory.name)/'workspace.json'
        path.write_text('broken',encoding='utf-8')
        with self.assertRaises(ApplicationError):
            Workspace(self.directory.name)
        self.assertEqual(path.read_text(),'broken')

    def test_http_lifecycle_and_origin_guards(self):
        server=make_server(self.workspace,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        host=f'127.0.0.1:{server.server_port}'
        def request(path,body=None,origin=None,override_host=None):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            headers={'Host':override_host or host}
            if body is not None:
                headers.update({'Content-Type':'application/json','Origin':origin or 'http://'+host})
            connection.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,headers)
            response=connection.getresponse()
            data=response.read()
            result=(response.status,data,response.getheader('Content-Security-Policy'))
            connection.close()
            return result
        try:
            for path in ['/','/app.js','/runtime.js','/ui.js','/scene.js','/runtime.css']:
                code,body,csp=request(path)
                self.assertEqual(code,200)
                self.assertIn("connect-src 'self'",csp)
            self.assertEqual(request('/api/app/zones',{'name':'Bad'},origin='https://other.example')[0],403)
            self.assertEqual(request('/api/app/workspace',override_host='other.example')[0],403)
            zone=self.create()
            self.assertEqual(request(f'/api/app/zones/{zone}/connect',{})[0],200)
            code,body,_=request(f'/api/app/zones/{zone}/snapshot')
            self.assertEqual(code,200)
            self.assertEqual(body,self.frame)
            self.assertEqual(request('/../.env')[0],404)
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':
    unittest.main()
