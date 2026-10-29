import http.client
import json
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from PIL import Image
import server
from playground.monitoring.controller import Monitoring


class MonitoringRouteTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        buffer=BytesIO();Image.new('RGB',(100,80)).save(buffer,'JPEG')
        self.body=buffer.getvalue()
        self.monitor=Monitoring(fetch=lambda camera:(self.body,{'X-Frame-Sequence':'1','X-Frame-Age-Ms':'0'}),
                                path=Path(self.folder.name)/'configuration.json')
        self.binding=patch.object(server,'monitoring',self.monitor);self.binding.start()
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.monitor.stop();self.http.shutdown();self.http.server_close();self.thread.join()
        self.binding.stop();self.folder.cleanup()

    def request(self,path,payload=None,origin='http://localhost:5051',host='localhost:5051'):
        connection=http.client.HTTPConnection('127.0.0.1',self.http.server_port)
        headers={'Host':host}
        if payload is not None:headers.update(Origin=origin,**{'Content-Type':'application/json'})
        connection.request('POST' if payload is not None else 'GET',path,
                           json.dumps(payload) if payload is not None else None,headers)
        response=connection.getresponse();body=response.read();connection.close()
        return response.status,body

    def test_page_assets_and_original_tools_still_available(self):
        for path in ('/','/monitoring','/monitoring.js','/monitoring.css'):
            code,body=self.request(path);self.assertEqual(code,200);self.assertGreater(len(body),100)

    def test_camera_save_snapshot_and_secret_redaction(self):
        code,body=self.request('/api/monitoring/connect',{'camera':{
            'url':'192.168.1.254:8080','username':'private-user','password':'private-password'}})
        self.assertEqual(code,200)
        self.assertNotIn(b'private-user',body);self.assertNotIn(b'private-password',body)
        state=json.loads(body);self.assertTrue(state['config']['camera']['credentials_configured'])
        code,body=self.request('/api/monitoring/snapshot');self.assertEqual(code,200);self.assertEqual(body,self.body)
        config=state['config'];config['zone'].update(polygon=[[1,1],[90,1],[90,70],[1,70]],frame_size=[100,80])
        code,body=self.request('/api/monitoring/save',config);self.assertEqual(code,200)
        self.assertEqual(len(json.loads(body)['config']['zone']['polygon']),4)
        code,body=self.request('/api/monitoring/prompt',{'sam_prompt':'forklift'});self.assertEqual(code,200)
        self.assertEqual(len(json.loads(body)['config']['zone']['polygon']),4)

    def test_cross_origin_and_invalid_settings_do_not_mutate(self):
        before=self.monitor.config.copy()
        self.assertEqual(self.request('/api/monitoring/save',{},origin='https://example.com')[0],403)
        self.assertEqual(self.request('/api/monitoring/connect',{'camera':{'url':'http://8.8.8.8'}})[0],400)
        self.assertEqual(self.request('/api/monitoring/save',{'rule':{'action':'scada'}})[0],400)
        self.assertEqual(self.request('/api/monitoring/status',host='example.com')[0],403)
        self.assertEqual(self.monitor.config,before)


if __name__=='__main__':unittest.main()
