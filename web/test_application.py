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
    def test_shared_buffer_does_not_fetch_per_consumer_or_block_status(self):
        entered,release=threading.Event(),threading.Event()
        calls=[]
        body=jpeg()
        def fetch(url):
            calls.append(1)
            if len(calls)==2:
                entered.set();release.wait(1)
            return body,{'X-Frame-Sequence':str(len(calls)),'X-Frame-Age-Ms':'0'}
        camera=Camera('192.168.1.50',fetch)
        camera.snapshot();camera.start()
        try:
            self.assertTrue(entered.wait(1))
            began=time.monotonic()
            for _ in range(100):
                self.assertEqual(camera.snapshot()[0],body)
                self.assertTrue(camera.status()['connected'])
            self.assertLess(time.monotonic()-began,.3)
            self.assertEqual(len(calls),2,'Consumers share the latest frame without extra upstream requests')
            release.set();camera.stop_event.wait(2.1)
            self.assertTrue(camera.status()['connected'],'Camera stays fresh without preview or inference consumers')
        finally:
            release.set();camera.stop()
        self.assertFalse(camera.status()['connected'])
        with self.assertRaises(OSError):camera.snapshot()

    def test_camera_polling_recovers_without_claiming_failed_frames_are_fresh(self):
        fail=threading.Event()
        sequence=[0]
        def fetch(url):
            if fail.is_set():raise OSError('Injected transport failure')
            sequence[0]+=1
            return jpeg(),{'X-Frame-Sequence':str(sequence[0]),'X-Frame-Age-Ms':'0'}
        camera=Camera('192.168.1.50',fetch)
        camera.snapshot();camera.start()
        def until(connected):
            deadline=time.monotonic()+1.5
            while time.monotonic()<deadline:
                if camera.status()['connected']==connected:return
                time.sleep(.01)
            self.fail('Camera did not reach the expected connection state')
        try:
            fail.set();until(False)
            self.assertIsNone(camera.jpeg)
            fail.clear();until(True)
            self.assertGreaterEqual(camera.status()['failures'],1)
        finally:camera.stop()

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
    def test_workspace_tag_folders_preserve_stable_zone_identity(self):
        zone=self.create()
        config=self.workspace.status()['workspace']
        config['name']='Company A'
        config['zones'][0].update(name='A-101',output='person_detect_A-101')
        view=self.workspace.save(config)['workspace']['zones'][0]
        self.assertEqual(view['id'],zone)
        self.assertEqual(view['tag_path'],['Company A','A-101','person_detect_A-101'])

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
            for path in ['/','/app.js','/runtime.js','/ui.js','/scene.js','/runtime.css','/camera-preview.js']:
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

    def test_fixed_zone_tags_survive_output_rename_and_zone_removal(self):
        def infer(frames,prompt,revision):
            for index,frame in enumerate(frames):
                yield dict(type='frame',frame_index=index,frame_sequence=frame['sequence'],prompt=prompt,
                    prompt_revision=revision,width=100,height=80,count=0,objects=[],session_id='isolated',elapsed_seconds=.01)
        self.workspace.infer=infer
        zone=self.configure_with(name='A-101',persistence=0)
        self.assertEqual(self.workspace.status()['workspace']['zones'][0]['tagKey'],'','No key before the first rule')
        self.workspace.configure(zone)
        self.assertEqual(self.workspace.status()['workspace']['zones'][0]['tagKey'],'A-101')
        self.workspace.enable(zone,True)
        deadline=time.monotonic()+7
        while time.monotonic()<deadline and self.workspace.observations.zones()['zones'][0]['State']!='Clear':
            time.sleep(.03)
        self.assertEqual(self.workspace.observations.zones()['zones'][0]['State'],'Clear')
        self.workspace.enable(zone,False)
        while self.workspace.monitors[zone].busy():
            time.sleep(.03)
        config=self.workspace.status()['workspace']
        config['zones'][0].update(name='Desk',output='person_on_desk',tagKey='Hijack')
        self.workspace.save(config)
        self.workspace.configure(zone)
        view=self.workspace.status()['workspace']['zones'][0]
        self.assertEqual(view['tagKey'],'A-101','Renames and client edits keep the tag key')
        signals=self.workspace.observations.snapshot()['assets'][0]['signals']
        self.assertEqual([s['signal_id'] for s in signals],['person_on_desk'],'The old output is removed, not left Unknown')
        tags=self.workspace.observations.zones()['zones'][0]
        self.assertEqual((tags['TagKey'],tags['OutputName'],tags['ZoneName']),('A-101','person_on_desk','Desk'))
        restored=Workspace(self.directory.name,fetch=self.workspace.fetch)
        try:
            self.assertEqual(restored.observations.zones()['zones'][0]['TagKey'],'A-101')
        finally:
            restored.close()
        config=self.workspace.status()['workspace']
        config['zones']=[]
        self.workspace.save(config)
        self.assertEqual(self.workspace.observations.snapshot()['assets'],[])
        self.assertEqual(self.workspace.observations.zones()['zones'],[])

    def test_opc_ua_network_access_needs_a_local_address_and_login(self):
        from unittest.mock import patch
        from services.application import transport_settings,INTEGRATION_DEFAULTS
        base=dict(INTEGRATION_DEFAULTS,opcEnabled=True,opcAccess='Network',opcHost='192.168.1.236')
        with patch('services.application.local_addresses',return_value=['192.168.1.236']):
            with patch('services.application.credentials_ready',return_value=False),self.assertRaises(ApplicationError) as caught:
                transport_settings(base)
            self.assertIn('VLOCK_OPCUA_SERVER_PASSWORD',str(caught.exception))
            with patch('services.application.credentials_ready',return_value=True):
                opcua=transport_settings(base)['opcua']
                self.assertEqual((opcua['access'],opcua['host']),('network','192.168.1.236'))
                with self.assertRaises(ApplicationError):
                    transport_settings(dict(base,opcHost='192.168.1.99'))
        with self.assertRaises(ApplicationError):
            transport_settings(dict(base,opcAccess='Everyone'))
        local=transport_settings(dict(INTEGRATION_DEFAULTS,opcEnabled=True))['opcua']
        self.assertEqual((local['access'],local['host']),('local','127.0.0.1'))
        self.assertIn('adapters',self.workspace.status()['capabilities']['opcua'])

    def test_zone_tag_routes_and_ignition_export(self):
        zone=self.configure_with(name='A-101')
        self.workspace.configure(zone)
        server=make_server(self.workspace,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            def get(path):
                connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                connection.request('GET',path,headers={'Host':f'127.0.0.1:{server.server_port}'})
                response=connection.getresponse()
                result=response.status,response.read(),response.getheader('Content-Disposition')
                connection.close()
                return result
            code,body,_=get('/api/v1/zones')
            self.assertEqual(code,200)
            self.assertEqual(json.loads(body)['zones'][0]['TagKey'],'A-101')
            code,body,_=get('/api/v1/zones/A-101')
            self.assertEqual((code,json.loads(body)['State']),(200,'Unknown'))
            self.assertEqual(get('/api/v1/zones/missing')[0],404)
            code,body,disposition=get('/api/app/ignition/vlock-zones.json')
            self.assertEqual(code,200)
            self.assertIn('attachment',disposition)
            self.assertEqual(json.loads(body)['tags'][1]['tags'][1]['name'],'A-101')
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_muse_proposal_route_sends_frame_only_on_request_and_saves_nothing(self):
        from services.vision.assistant import AssistantError
        calls=[]
        class Assistant:
            def status(self):return dict(provider='Meta Model API',model='muse-spark-1.3',configured=True)
            def propose(self,text,draft,jpeg=None):
                calls.append((text,draft,jpeg))
                if text=='fail':raise AssistantError('Meta rate limit or quota reached. Wait and try again.',502)
                area=dict(method='sam_object',object='aisle',description='Aisle',box=[.1,.1,.6,.9])
                return dict(proposal=dict(supported=True,target='forklift',area=area),model='muse-spark-1.3',frame_included=jpeg is not None,elapsed_seconds=.1)
        regions=[]
        def outline(jpeg,prompt):
            regions.append((jpeg,prompt))
            return [dict(polygon=[[.2,.2],[.8,.2],[.8,.8]],area=.2)]
        self.workspace.assistant=Assistant()
        self.workspace.regions=outline
        zone=self.create()
        before=self.workspace.status()['workspace']
        self.assertEqual(self.workspace.status()['capabilities']['assistant']['model'],'muse-spark-1.3')
        server=make_server(self.workspace,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        host=f'127.0.0.1:{server.server_port}'
        def post(body,origin=None):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            connection.request('POST',f'/api/app/zones/{zone}/propose',json.dumps(body),
                {'Host':host,'Content-Type':'application/json','Origin':origin or 'http://'+host})
            response=connection.getresponse()
            result=(response.status,json.loads(response.read()))
            connection.close()
            return result
        try:
            self.assertEqual(post({'text':'Watch for forklifts'},origin='https://other.example')[0],403)
            code,body=post({'text':'Watch for forklifts'})
            self.assertEqual(code,200)
            self.assertFalse(body['frame_included'])
            self.assertIsNone(calls[-1][2])
            self.assertEqual(calls[-1][1]['target'],'person')
            self.assertEqual(post({'text':'Watch','includeFrame':'yes'})[0],400)
            self.assertEqual(post({'text':'Watch','includeFrame':True})[0],409,'Frame requires a connected camera')
            self.workspace.connect(zone)
            code,body=post({'text':'Watch','includeFrame':True})
            self.assertEqual(code,200)
            self.assertEqual(calls[-1][2],self.frame)
            self.assertEqual(body['proposal']['area']['source'],'sam')
            self.assertEqual(regions[-1],(self.frame,'aisle'),'SAM outlines the named region on the local frame')
            code,body=post({'text':'Watch'})
            self.assertIsNone(calls[-1][2],'Text-only requests never send the frame to Muse')
            self.assertEqual(regions[-1][0],self.frame,'SAM still uses the local frame')
            self.assertEqual(post({'text':'fail'}),(502,{'error':'Meta rate limit or quota reached. Wait and try again.'}))
        finally:
            server.shutdown();server.server_close();thread.join()
        after=self.workspace.status()['workspace']
        self.assertEqual(after['zones'][0]['target'],before['zones'][0]['target'])
        self.assertFalse(after['zones'][0]['configured'])

    def test_area_proposal_falls_back_from_sam_to_muse_box(self):
        from services.vision.masks import SegmentationError
        area=dict(method='sam_object',object='table',description='Table',box=[.1,.2,.5,.6])
        def busy(jpeg,prompt):raise SegmentationError('Local SAM is busy.',409)
        self.workspace.regions=busy
        result=self.workspace.propose_area(area,self.frame)
        self.assertEqual(result['source'],'muse_box')
        self.assertEqual(result['polygon'],[[.1,.2],[.5,.2],[.5,.6],[.1,.6]])
        self.assertIn('busy',result['note'])
        self.workspace.regions=lambda jpeg,prompt:[]
        none=self.workspace.propose_area(dict(area,box=None),self.frame)
        self.assertIsNone(none['polygon'])
        self.assertIn('found no',none['note'])
        self.assertIsNone(self.workspace.propose_area(dict(area,box=None),None)['polygon'])
        self.assertEqual(self.workspace.propose_area(dict(area,method='whole_frame'),None)['source'],'whole_frame')
        self.assertIsNone(self.workspace.propose_area(dict(area,method='keep_current'),self.frame)['polygon'])

    def test_saving_integration_profile_starts_and_stops_opc_ua_server(self):
        from services.vlock.test_transports import free_port
        port=free_port()
        config=self.workspace.status()['workspace']
        config['integration'].update(opcEnabled=True,opcPort=port)
        self.workspace.save(config)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline and self.workspace.status()['integrations']['opcua']['status']!='running':
            time.sleep(.1)
        self.assertEqual(self.workspace.status()['integrations']['opcua']['status'],'running')
        for change in [dict(opcMode='client'),dict(opcHost='192.168.1.20'),dict(mqttEnabled=True,mqttMode='host broker — planned'),dict(opcPort=4845.5)]:
            bad=self.workspace.status()['workspace']
            bad['integration'].update(change)
            with self.subTest(change=change),self.assertRaises(ApplicationError):
                self.workspace.save(bad)
        config=self.workspace.status()['workspace']
        config['integration'].update(opcEnabled=False)
        self.workspace.save(config)
        self.assertEqual(self.workspace.status()['integrations']['opcua']['status'],'disabled')

    def test_enable_waits_for_sam_worker(self):
        class Worker:
            state='loading'
            def status(self):return dict(state=self.state,message='Loading SAM 3.1 onto the GPU.')
        self.workspace.worker=Worker()
        self.workspace.infer=lambda frames,prompt,revision:iter(())
        zone=self.create()
        self.workspace.connect(zone)
        config=self.workspace.status()['workspace']
        config['zones'][0].update(zone=[[.1,.1],[.9,.1],[.9,.9],[.1,.9]],areaSelected=True)
        self.workspace.save(config)
        self.workspace.configure(zone)
        with self.assertRaises(ApplicationError) as caught:
            self.workspace.enable(zone,True)
        self.assertEqual(caught.exception.status,409)
        self.assertEqual(self.workspace.status()['sam']['state'],'loading')

    def configure_with(self,**changes):
        zone=self.create()
        self.workspace.connect(zone)
        config=self.workspace.status()['workspace']
        config['zones'][0].update(dict(zone=[[.1,.1],[.9,.1],[.9,.9],[.1,.9]],areaSelected=True)|changes)
        self.workspace.save(config)
        return zone

    def test_configure_two_objects_and_reject_more(self):
        zone=self.configure_with(target='person',extraConditions=[dict(object='dog',relation='entirely inside area')],ruleJoin='ANY (OR)')
        self.workspace.configure(zone)
        monitor=self.workspace.monitors[zone].config
        self.assertEqual(monitor['second'],{'prompt':'dog','condition':'mask_inside_zone'})
        self.assertEqual(monitor['rule']['join'],'any')
        self.assertEqual(self.workspace.status()['workspace']['zones'][0]['runtime']['objects'],2)
        for changes in [dict(extraConditions=[dict(object='dog',relation='overlaps area'),dict(object='cat',relation='overlaps area')]),
                        dict(extraConditions=[dict(object='Person',relation='overlaps area')]),
                        dict(extraConditions=[dict(object='dog',relation='crosses line')]),
                        dict(extraConditions=[dict(object='dog',relation='overlaps area')],ruleJoin='XOR')]:
            config=self.workspace.status()['workspace']
            config['zones'][0].update(changes)
            self.workspace.save(config)
            with self.subTest(changes=changes),self.assertRaises(ApplicationError):
                self.workspace.configure(zone)
        config=self.workspace.status()['workspace']
        config['zones'][0].update(extraConditions=[],ruleJoin='ALL (AND)')
        self.workspace.save(config)
        self.workspace.configure(zone)
        self.assertIsNone(self.workspace.monitors[zone].config['second'],'Removing the second object clears it')

    def test_saved_one_object_workspace_still_configures(self):
        zone=self.configure_with(target='hand',extraConditions=[],ruleJoin='ANY (OR)')
        restored=Workspace(self.directory.name,fetch=self.workspace.fetch)
        try:
            restored.connect(zone)
            restored.configure(zone)
            self.assertIsNone(restored.monitors[zone].config['second'])
            self.assertEqual(restored.monitors[zone].config['sam_prompt'],'hand')
        finally:
            restored.close()

    def test_two_object_count_and_check_time_in_status(self):
        def infer(frames,prompt,revision):
            mask=Image.new('L',(100,80))
            ImageDraw.Draw(mask).rectangle((20,20,40,40),fill=255)
            objects=[dict(object_id=1,score=.9,mask=encode_mask(mask),bbox_xywh=[.2,.25,.2,.25])]*(2 if prompt=='person' else 1)
            for index,frame in enumerate(frames):
                yield dict(type='frame',frame_index=index,frame_sequence=frame['sequence'],prompt=prompt,prompt_revision=revision,
                    width=100,height=80,count=len(objects),objects=objects,session_id='isolated',elapsed_seconds=.01)
        self.workspace.infer=infer
        zone=self.configure_with(target='person',outputType='count',extraConditions=[dict(object='dog',relation='overlaps area')],persistence=0)
        self.workspace.configure(zone)
        self.workspace.enable(zone,True)
        deadline=time.monotonic()+7
        while time.monotonic()<deadline:
            runtime=self.workspace.status()['workspace']['zones'][0]['runtime']
            if runtime['state']=='Valid':break
            time.sleep(.03)
        self.assertEqual(runtime['value'],{'person':2,'dog':1})
        self.assertIsInstance(runtime['check_ms'],float)
        signal=self.workspace.observations.snapshot()['assets'][0]['signals'][0]
        self.assertEqual(signal['value'],{'person':2,'dog':1})
        self.workspace.enable(zone,False)

    def test_unsupported_rule_features_are_not_silently_ignored(self):
        zone=self.create()
        self.workspace.connect(zone)
        for changes in [dict(extraConditions=[dict(object='dog',relation='overlaps area'),dict(object='cat',relation='overlaps area')]),
                        dict(allowRemote=True),dict(minConfidence=75),dict(recheck='Cloud vision model — planned')]:
            config=self.workspace.status()['workspace']
            config['zones'][0].update(dict(zone=[[.1,.1],[.9,.1],[.9,.9],[.1,.9]],areaSelected=True,
                extraConditions=[],allowRemote=False,minConfidence=0,recheck='None')|changes)
            self.workspace.save(config)
            with self.subTest(changes=changes),self.assertRaises(ApplicationError):
                self.workspace.configure(zone)


if __name__=='__main__':
    unittest.main()
