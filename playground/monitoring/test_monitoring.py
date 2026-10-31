import copy
import json
import sys
import tempfile
import threading
import time
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'segmentation'))
from playground.monitoring.configuration import DEFAULT, Store, validate, public, camera_url
from playground.monitoring.zone_rules import evaluate, RuleState
from playground.monitoring.controller import Monitoring
from playground.monitoring.camera_source import snapshot
from video_tracking import encode_mask


def config():
    value=copy.deepcopy(DEFAULT)
    value['camera']['frame_size']=[100,80]
    value['zone'].update(polygon=[[0,0],[49,0],[49,79],[0,79]],frame_size=[100,80])
    value['rule']['persistence_seconds']=0
    return value


def result(mask=None,index=0,prompt='person',revision=1):
    if mask is None:
        mask=Image.new('L',(100,80));ImageDraw.Draw(mask).rectangle((40,30,59,49),fill=255)
    return dict(type='frame',width=100,height=80,objects=[dict(object_id=8,score=0.9,
        bbox_xywh=[0.4,0.375,0.2,0.25],mask=encode_mask(mask))],count=1,frame_index=index,
        frame_sequence=str(index+1),prompt=prompt,prompt_revision=revision,session_id='test-session',
        elapsed_seconds=0.1,peak_vram_mb=100,model='sam-3.1')


def jpeg():
    output=BytesIO();Image.new('RGB',(100,80)).save(output,'JPEG');return output.getvalue()


class ConfigurationTests(unittest.TestCase):
    def test_saved_config_survives_restart_and_redacts_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'configuration.json')
            value=config();value['camera'].update(username='private-user',password='private-password')
            store.save(validate(value,value,require_zone=True))
            loaded=Store(store.path).load()
            self.assertEqual(loaded,value)
            rendered=json.dumps(public(loaded))
            self.assertNotIn('private-user',rendered);self.assertNotIn('private-password',rendered)
            self.assertTrue(public(loaded)['camera']['credentials_configured'])
            changed=validate({'sam_prompt':'forklift'},loaded,require_zone=True)
            self.assertEqual(changed['zone'],loaded['zone'])
            self.assertEqual(changed['camera']['password'],'private-password')

    def test_lan_url_and_credentials_validation(self):
        self.assertEqual(camera_url('192.168.1.254:8080'),'http://192.168.1.254:8080')
        self.assertEqual(camera_url('http://192.168.1.254:8080/snapshot.jpg'),'http://192.168.1.254:8080')
        for value in ('http://user:secret@192.168.1.2','http://8.8.8.8','http://localhost:8080','rtsp://192.168.1.2','http://192.168.1.2/other','http://192.168.1.2?token=private','192.168.1.2:0'):
            with self.assertRaises(ValueError):camera_url(value)
        with self.assertRaises(ValueError):validate({'camera':{'password':'bad\nvalue'}})

    def test_bad_polygons_and_rules_rejected(self):
        for points in ([[1,1],[99,79],[1,79],[99,1]], [[0,0],[0,0],[3,3]], [[0,0],[100,0],[0,80]], [[0,0],[1,1],[2,2]]):
            value=config();value['zone']['polygon']=points
            with self.assertRaises(ValueError):validate(value,value)
        for change in ({'min_overlap_ratio':0},{'persistence_seconds':float('nan')},{'action':'scada'},{'condition':'run_code'}):
            value=config();value['rule'].update(change)
            with self.assertRaises(ValueError):validate(value,value)

    def test_bad_saved_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'configuration.json';path.write_text('broken-json')
            with self.assertRaises(ValueError):Store(path).load()
            self.assertEqual(path.read_text(),'broken-json')

    def test_auth_stays_in_request_and_plain_camera_reuses_relay(self):
        camera=config()['camera'];calls=[]
        self.assertEqual(snapshot(camera,lambda target:(calls.append(target) or b'original',{}))[0],b'original')
        self.assertEqual(calls,['192.168.1.254:8080'])
        camera.update(username='user',password='password')
        with patch('playground.monitoring.camera_source.http.client.HTTPConnection') as factory:
            response=factory.return_value.getresponse.return_value;response.status=200
            response.getheader.side_effect=lambda name,default='':{'Content-Type':'image/jpeg','X-Frame-Sequence':'1','X-Frame-Age-Ms':'2'}.get(name,default)
            response.read.return_value=jpeg()
            self.assertEqual(snapshot(camera,None)[0],jpeg())
            self.assertIn('Authorization',factory.return_value.request.call_args.kwargs['headers'])
            factory.return_value.close.assert_called_once()


class ZoneTests(unittest.TestCase):
    def test_actual_mask_overlap_inside_and_absence(self):
        value=config();matched,details=evaluate(result(),value)
        self.assertTrue(matched);self.assertEqual(details[0]['overlap_ratio'],0.5)
        value['rule']['min_overlap_ratio']=0.6
        self.assertFalse(evaluate(result(),value)[0])
        value['rule']['condition']='mask_inside_zone'
        self.assertFalse(evaluate(result(),value)[0])
        mask=Image.new('L',(100,80));ImageDraw.Draw(mask).rectangle((10,10,20,20),fill=255)
        self.assertTrue(evaluate(result(mask),value)[0])
        value['rule']['condition']='object_absent'
        value['rule']['min_overlap_ratio']=0.1
        empty=result();empty.update(objects=[],count=0)
        self.assertTrue(evaluate(empty,value)[0])
        self.assertFalse(evaluate(result(),value)[0])

    def test_box_overlap_does_not_replace_mask_geometry(self):
        value=config();value['zone']['polygon']=[[40,0],[59,0],[59,79],[40,79]]
        mask=Image.new('L',(100,80));mask.putpixel((10,40),255);mask.putpixel((90,40),255)
        predicted=result(mask);predicted['objects'][0]['bbox_xywh']=[0.1,0.5,0.8,0.1]
        self.assertFalse(evaluate(predicted,value)[0])

    def test_invalid_or_empty_masks_and_resolution_are_not_absence(self):
        for predicted in (result(Image.new('L',(100,80))),result(Image.new('L',(50,40)))):
            with self.assertRaises(ValueError):evaluate(predicted,config())
        predicted=result();predicted['width']=200
        with self.assertRaises(ValueError):evaluate(predicted,config())
        predicted=result();predicted['objects'][0]['mask']['counts']=[-1,8001]
        with self.assertRaises(ValueError):evaluate(predicted,config())


class RuleTests(unittest.TestCase):
    def test_persistence_transitions_debounce_and_freshness(self):
        now=[100.0];state=RuleState(1,clock=lambda:now[0])
        self.assertFalse(state.observe(True,99));self.assertEqual(state.state,'Unknown')
        self.assertFalse(state.observe(True,99.5))
        self.assertTrue(state.observe(True,100));self.assertEqual(state.state,'Warning')
        now[0]=101;self.assertFalse(state.observe(True,101))
        now[0]=102;self.assertFalse(state.observe(False,102));self.assertEqual(state.state,'Warning')
        now[0]=103;self.assertTrue(state.observe(False,103));self.assertEqual(state.state,'Normal')
        now[0]=114;self.assertTrue(state.expire());self.assertEqual(state.state,'Unknown')
        self.assertFalse(state.observe(False,103));self.assertEqual(state.state,'Unknown')

    def test_duplicate_or_missing_observations_reset_confirmation(self):
        state=RuleState(0,clock=lambda:100)
        state.observe(True,99);state.observe(True,99)
        self.assertEqual(state.state,'Unknown')
        state.observe(True,99.1);self.assertEqual(state.state,'Unknown')
        state.unavailable('Disconnected');state.observe(False,99.2)
        self.assertEqual(state.state,'Unknown')

    def test_large_gap_and_future_timestamp_are_unknown(self):
        now=[100]
        state=RuleState(0,clock=lambda:now[0])
        state.observe(True,99);state.observe(True,100)
        self.assertEqual(state.state,'Warning')
        now[0]=111
        self.assertTrue(state.observe(True,111));self.assertEqual(state.state,'Unknown')
        self.assertFalse(state.observe(False,112));self.assertEqual(state.state,'Unknown')


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.path=Path(self.directory.name)/'configuration.json'
        self.monitor=Monitoring(fetch=lambda camera:(jpeg(),{'X-Frame-Sequence':'1','X-Frame-Age-Ms':'0'}),path=self.path)
        self.monitor.connect({'camera':config()['camera']})
        self.monitor.save(config())

    def tearDown(self):
        self.monitor.stop()
        if self.monitor.thread:self.monitor.thread.join(3)
        self.directory.cleanup()

    def test_warning_once_prompt_preserves_zone_and_events_survive_restart(self):
        before=time.monotonic()-1
        for index in range(4):
            row=result(index=index)
            self.monitor.publish(row,{'jpeg':jpeg(),'captured_at':before+index*0.1},0,self.monitor.config)
        self.assertEqual(self.monitor.status()['state'],'Warning')
        self.assertEqual([e['type'] for e in self.monitor.events],['warning'])
        self.monitor.change_prompt('forklift')
        self.assertEqual(self.monitor.config['zone'],config()['zone'])
        self.assertIsNone(self.monitor.status()['result'])
        restored=Monitoring(fetch=None,path=self.path)
        self.assertEqual(restored.config['sam_prompt'],'forklift')
        self.assertEqual(len(restored.events),2)
        self.assertFalse(restored.running)

    def test_stop_and_prompt_change_discard_inflight_outputs(self):
        entered,release=threading.Event(),threading.Event()
        counter=[0]
        def fetch(camera):
            counter[0]+=1
            return jpeg(),{'X-Frame-Sequence':str(counter[0]),'X-Frame-Age-Ms':'0'}
        def infer(frames,prompt,revision):
            entered.set();release.wait(4)
            for index,frame in enumerate(frames):
                row=result(index=index,prompt=prompt,revision=revision);row['frame_sequence']=frame['sequence']
                yield row
        self.monitor.fetch,self.monitor.infer=fetch,infer
        self.monitor.start()
        try:
            self.assertTrue(entered.wait(3))
            self.monitor.change_prompt('forklift')
            self.monitor.stop();release.set();self.monitor.thread.join(3)
            self.assertIsNone(self.monitor.status()['result'])
            self.assertFalse(any(e['type']=='warning' for e in self.monitor.events))
            self.assertEqual(self.monitor.status()['state'],'Unknown')
        finally:release.set()

    def test_camera_failure_marks_unknown_and_clears_result(self):
        self.monitor.rule.state='Normal'
        self.monitor.fetch=lambda camera:(_ for _ in ()).throw(OSError('sensitive camera value'))
        with self.assertRaises(OSError) as caught:self.monitor.snapshot()
        self.assertNotIn('sensitive',str(caught.exception))
        self.assertEqual(self.monitor.status()['state'],'Unknown')

    def test_newest_overlay_preserves_every_mask_observation_and_warning(self):
        before=time.monotonic()-1
        with patch('playground.monitoring.controller.render',return_value='newest-overlay') as render:
            for index in range(4):
                self.monitor.publish(result(index=index),
                    {'jpeg':jpeg(),'captured_at':before+index*.1},0,self.monitor.config,
                    render_overlay=index==3)
                if index<3:self.assertIsNone(self.monitor.status()['result'])
        render.assert_called_once()
        rows=self.monitor.results(0)['frames']
        self.assertEqual([r['frame_index'] for r in rows],[0,1,2,3])
        for index,row in enumerate(rows):
            self.assertEqual(row['objects'],result(index=index)['objects'])
            self.assertEqual(row['zone_detections'][0]['overlap_ratio'],.5)
        state=self.monitor.status()
        self.assertEqual(state['result']['frame_index'],3)
        self.assertEqual(state['result']['annotated_image'],'newest-overlay')
        self.assertTrue(state['warning_active'])
        self.assertEqual([e['type'] for e in self.monitor.events],['warning'])

    def test_collection_keeps_spacing_and_uniqueness_without_final_wait(self):
        waits=[];calls=[];sequences=iter(['1','1','2','3','4'])
        def fetch(camera):
            return jpeg(),{'X-Frame-Sequence':next(sequences),'X-Frame-Age-Ms':'0'}
        def wait(seconds):
            waits.append(seconds)
            return False
        def infer(frames,prompt,revision):
            calls.append([frame['sequence'] for frame in frames])
            self.monitor.cancel.set()
            return (row for row in ())
        self.monitor.fetch,self.monitor.infer=fetch,infer
        with patch.object(self.monitor.cancel,'wait',side_effect=wait):self.monitor.loop()
        self.assertEqual(calls,[['1','2','3','4']])
        # Three inter-frame waits plus one duplicate retry; none after frame four.
        self.assertEqual(waits,[.25]*4)

    def test_skipped_overlays_never_make_old_observations_fresh(self):
        before=time.monotonic()-20
        with patch('playground.monitoring.controller.render',return_value='old-overlay'):
            for index in range(4):
                self.monitor.publish(result(index=index),
                    {'jpeg':jpeg(),'captured_at':before+index*.1},0,self.monitor.config,
                    render_overlay=index==3)
        self.assertEqual(len(self.monitor.results(0)['frames']),4)
        state=self.monitor.status()
        self.assertEqual(state['state'],'Unknown')
        self.assertFalse(state['warning_active'])
        self.assertTrue(state['result']['stale'])
        self.assertGreater(state['result']['age_seconds'],19)

    def test_corrupt_monitoring_config_does_not_disable_existing_app(self):
        path=Path(self.directory.name)/'corrupt.json';path.write_text('invalid-json')
        monitor=Monitoring(fetch=None,path=path)
        self.assertEqual(monitor.status()['state'],'Unknown')
        self.assertIn('invalid',monitor.status()['reason'])
        with self.assertRaises(ValueError):monitor.connect({})
        self.assertEqual(path.read_text(),'invalid-json')
        monitor.save(config())
        self.assertIsNone(monitor.config_error)

    def test_event_log_action_does_not_activate_warning_output(self):
        value=config();value['rule']['action']='event_log';self.monitor.save(value)
        before=time.monotonic()-1
        for index in range(2):
            self.monitor.publish(result(index=index),{'jpeg':jpeg(),'captured_at':before+index*0.1},0,value)
        state=self.monitor.status()
        self.assertEqual(state['state'],'Warning')
        self.assertFalse(state['warning_active'])
        self.assertEqual(state['events'][-1]['type'],'rule_triggered')


if __name__=='__main__':unittest.main()
