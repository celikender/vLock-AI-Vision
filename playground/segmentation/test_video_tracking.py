"""Offline video-session, mask contract, and live prompt cancellation checks."""
import json
import threading
import time
import unittest
import sys
from types import SimpleNamespace
from contextlib import nullcontext
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from monitor import Monitor
import local_worker
from video_tracking import track_window, encode_mask, decode_mask, serialize_frame


class FakePredictor:
    def __init__(self):
        self.requests=[]
        self.sessions=0
        self.closed_streams=0

    def handle_request(self, request):
        self.requests.append(request.copy())
        if request['type']=='start_session':
            self.sessions+=1
            return {'session_id':f'session-{self.sessions}'}
        if request['type']=='add_prompt':
            return output(0)
        return {'is_success':True}

    def handle_stream_request(self, request):
        self.requests.append(request.copy())
        try:
            for index in range(4):
                yield output(index)
        finally:
            self.closed_streams+=1


def output(index):
    mask=Image.new('L',(4,3))
    mask.putpixel((index%4,1),255)
    return {'frame_index':index,'outputs':{'out_obj_ids':[7],
        'out_binary_masks':[mask],'out_probs':[0.875],
        'out_boxes_xywh':[[index/4,1/3,1/4,1/3]]}}


def metadata():
    return [{'sequence':str(i+100),'size':[4,3]} for i in range(4)]


class VideoTests(unittest.TestCase):
    def test_prompts_propagation_ids_and_exact_rle_roundtrip(self):
        model=FakePredictor()
        for revision,prompt in enumerate(('person','forklift')):
            rows=list(track_window(model,'camera-window',prompt,revision,metadata()))
            self.assertEqual([r['frame_index'] for r in rows],[0,1,2,3])
            self.assertEqual([r['frame_sequence'] for r in rows],['100','101','102','103'])
            self.assertEqual({r['prompt'] for r in rows},{prompt})
            self.assertEqual({r['session_id'] for r in rows},{f'session-{revision+1}'})
            for index,row in enumerate(rows):
                obj=row['objects'][0]
                self.assertEqual(obj['object_id'],7)
                self.assertEqual(obj['score'],0.875)
                self.assertEqual(decode_mask(obj['mask']).tobytes(),output(index)['outputs']['out_binary_masks'][0].tobytes())
                json.dumps(row,allow_nan=False)
        self.assertEqual([r['text'] for r in model.requests if r['type']=='add_prompt'],['person','forklift'])
        self.assertEqual(sum(r['type']=='close_session' for r in model.requests),2)
        self.assertEqual(model.closed_streams,2)

    def test_cancel_and_error_close_session(self):
        model=FakePredictor()
        stream=track_window(model,'window','person',1,metadata())
        next(stream)
        stream.close()
        self.assertEqual(model.requests[-1]['type'],'close_session')
        self.assertEqual(model.closed_streams,1)
        with patch.object(model,'handle_stream_request',return_value=(r for r in [])):
            with self.assertRaises(ValueError):
                list(track_window(model,'window','person',1,metadata()))
        self.assertEqual(model.requests[-1]['type'],'close_session')

    def test_mask_empty_full_and_missing_scores(self):
        for value in (0,255):
            mask=Image.new('L',(5,3),value)
            self.assertEqual(decode_mask(encode_mask(mask)).tobytes(),mask.tobytes())
        response=output(0)
        del response['outputs']['out_probs']
        row=serialize_frame(response,'session','person',1,metadata())
        self.assertIsNone(row['objects'][0]['score'])
        response['outputs']['out_obj_ids']=[]
        with self.assertRaises(ValueError):
            serialize_frame(response,'session','person',1,metadata())

    def test_prompt_change_drops_inflight_results_without_stopping_camera(self):
        entered,release,done=threading.Event(),threading.Event(),threading.Event()
        calls=[]
        sequence=[0]
        jpeg=BytesIO();Image.new('RGB',(4,3)).save(jpeg,'JPEG')
        def fetch(address):
            sequence[0]+=1
            return jpeg.getvalue(),{'X-Frame-Sequence':str(sequence[0]),'X-Frame-Age-Ms':'0'}
        def infer(frames,prompt,revision):
            calls.append(prompt)
            if prompt=='person':
                entered.set()
                release.wait(5)
            for i in range(4):
                row=serialize_frame(output(i),prompt,prompt,revision,[{'sequence':f['sequence'],'size':[4,3]} for f in frames])
                row.update(elapsed_seconds=0.1,peak_vram_mb=100)
                yield row
            if prompt=='forklift':
                done.set()
        monitor=Monitor(fetch=fetch,video_infer=infer)
        monitor.start('192.168.1.50','person','video_tracking')
        try:
            self.assertTrue(entered.wait(3))
            monitor.change_prompt('forklift')
            self.assertIsNone(monitor.status()['result'])
            release.set()
            self.assertTrue(done.wait(4))
            self.assertEqual(calls[:2],['person','forklift'])
            rows=monitor.frames_since(0)['frames']
            self.assertEqual(len(rows),4)
            self.assertEqual({r['prompt'] for r in rows},{'forklift'})
        finally:
            monitor.stop();release.set();monitor.thread.join(3)
        self.assertIsNone(monitor.status()['result'])

    def test_worker_rejects_invalid_windows_and_releases_lock(self):
        client=local_worker.app.test_client()
        for data in ({'prompt':''},{'prompt':'person','frames':'[]'},
                     {'prompt':'person','frames':'not-json'}):
            response=client.post('/video/track',data=data,base_url='http://localhost:5052')
            self.assertEqual(response.status_code,400)
            self.assertFalse(local_worker.lock.locked())

    def test_history_refreshes_stale_age_and_hides_internal_clock(self):
        monitor=Monitor()
        monitor.output_id=1
        monitor.video_results.append({'output_id':1,'_observed_at':time.monotonic()-15,
                                      'age_seconds':0,'stale':False})
        row=monitor.frames_since(0)['frames'][0]
        self.assertTrue(row['stale'])
        self.assertGreaterEqual(row['age_seconds'],15)
        self.assertNotIn('_observed_at',row)
        self.assertEqual(monitor.frames_since(1)['frames'],[])

    def test_worker_model_is_shared_across_video_prompts_and_cleanup(self):
        model=FakePredictor()
        fake=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True,
            reset_peak_memory_stats=lambda:None,max_memory_allocated=lambda:1024**2),
            inference_mode=nullcontext,autocast=lambda *a,**k:nullcontext(),bfloat16='bf16')
        buffer=BytesIO();Image.new('RGB',(4,3)).save(buffer,'JPEG')
        jpeg=buffer.getvalue()
        with patch.dict(sys.modules,{'torch':fake,'sam3':SimpleNamespace(),
                'sam3.model_builder':SimpleNamespace(build_sam3_predictor=lambda **kwargs:model)}), \
                patch('local_worker.checkpoint',return_value='cached-checkpoint'), \
                patch('local_worker.predictor',None),patch('local_worker.model_loads',0):
            client=local_worker.app.test_client()
            for prompt in ('person','forklift'):
                response=client.post('/video/track',base_url='http://localhost:5052',data={
                    'prompt':prompt,'revision':'1','frames':json.dumps([{'sequence':str(i)} for i in range(4)]),
                    'frame':[(BytesIO(jpeg),f'{i}.jpg') for i in range(4)]})
                self.assertEqual(response.status_code,200)
                rows=[json.loads(line) for line in response.data.splitlines()]
                response.close()
                self.assertEqual(len(rows),4)
                self.assertEqual({r['prompt'] for r in rows},{prompt})
                self.assertEqual({r['model_loads'] for r in rows},{1})
                self.assertFalse(local_worker.lock.locked())
            self.assertIs(local_worker.predictor,model)
            self.assertEqual(local_worker.model_loads,1)
            # A client disconnect while a window is streaming must free its session/lock.
            response=client.post('/video/track',base_url='http://localhost:5052',data={
                'prompt':'person','frames':json.dumps([{'sequence':str(i)} for i in range(4)]),
                'frame':[(BytesIO(jpeg),f'{i}.jpg') for i in range(4)]})
            response.close()
            self.assertFalse(local_worker.lock.locked())
        self.assertEqual(sum(r['type']=='close_session' for r in model.requests),3)


if __name__=='__main__':
    unittest.main()
