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
from services.vision.video import encode_mask
from PIL import ImageDraw
import time


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
            for path in ['/api/v1/assets','/api/v1/health','/api/v1/events?limit=5']:
                code,body,_=request(path)
                self.assertEqual(code,200)
                self.assertEqual(json.loads(body)['schema_version'],1)
            self.assertEqual(request('/api/v1/events?limit=999')[0],400)
            self.assertEqual(request('/api/v1/events?after=-1')[0],400)
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

    def test_local_sam_path_active_clear_failure_and_stop(self):
        mode=['active']
        def infer(frames,prompt,revision):
            if mode[0]=='fail':
                raise OSError('Injected worker loss')
            mask=Image.new('L',(100,80))
            ImageDraw.Draw(mask).rectangle((20,20,40,40),fill=255)
            for index,frame in enumerate(frames):
                objects=[dict(object_id=1,score=.9,mask=encode_mask(mask),bbox_xywh=[.2,.25,.2,.25])] if mode[0]=='active' else []
                yield dict(type='frame',frame_index=index,frame_sequence=frame['sequence'],
                    prompt=prompt,prompt_revision=revision,width=100,height=80,count=len(objects),objects=objects,
                    session_id='isolated-session',elapsed_seconds=.01)
        self.workspace.infer=infer
        zone=self.create()
        self.workspace.connect(zone)
        config=self.workspace.status()['workspace']
        config['zones'][0].update(zone=[[.1,.1],[.9,.1],[.9,.9],[.1,.9]],areaSelected=True,persistence=0)
        self.workspace.save(config)
        self.workspace.configure(zone)
        self.workspace.enable(zone,True)
        def until(state):
            deadline=time.monotonic()+7
            while time.monotonic()<deadline:
                view=self.workspace.status()['workspace']['zones'][0]
                if view['runtime']['state']==state:return view
                time.sleep(.03)
            self.fail('Expected isolated monitoring state: '+state)
        active=until('Active')
        self.assertIs(active['runtime']['value'],True)
        self.assertTrue(active['runtime']['valid'])
        self.assertEqual(active['runtime']['count'],1)
        asset=self.workspace.observations.snapshot()['assets'][0]
        self.assertIs(asset['inhibit'],True)
        self.assertEqual(asset['signals'][0]['signal_id'],'zone_condition')
        self.assertEqual(self.workspace.analyzed(zone)[:8],b'\x89PNG\r\n\x1a\n')
        with self.assertRaises(ApplicationError):
            self.workspace.save(self.workspace.status()['workspace'])
        mode[0]='clear'
        clear=until('Clear')
        self.assertIs(clear['runtime']['value'],False)
        self.assertIsNone(clear['runtime']['score'])
        self.assertIs(self.workspace.observations.snapshot()['assets'][0]['inhibit'],False)
        mode[0]='fail'
        unknown=until('Unknown')
        self.assertFalse(unknown['runtime']['valid'])
        self.assertIsNone(unknown['runtime']['value'])
        self.assertIsNone(self.workspace.observations.snapshot()['assets'][0]['inhibit'])
        self.workspace.enable(zone,False)
        self.assertFalse(self.workspace.status()['workspace']['zones'][0]['runtime']['enabled'])
        self.assertIsNone(self.workspace.observations.snapshot()['assets'][0]['inhibit'])
        with self.assertRaises(ApplicationError):
            self.workspace.analyzed(zone)

    def test_unsupported_rule_features_are_not_silently_ignored(self):
        zone=self.create()
        self.workspace.connect(zone)
        for changes in [dict(extraConditions=[dict(object='dog',relation='overlaps area')]),
                        dict(allowRemote=True),dict(minConfidence=75),dict(recheck='Cloud vision model — planned')]:
            config=self.workspace.status()['workspace']
            config['zones'][0].update(dict(zone=[[.1,.1],[.9,.1],[.9,.9],[.1,.9]],areaSelected=True,
                extraConditions=[],allowRemote=False,minConfidence=0,recheck='None')|changes)
            self.workspace.save(config)
            with self.subTest(changes=changes),self.assertRaises(ApplicationError):
                self.workspace.configure(zone)


if __name__=='__main__':
    unittest.main()
