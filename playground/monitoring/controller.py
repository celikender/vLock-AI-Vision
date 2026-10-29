"""Monitoring configuration, bounded SAM windows and local warning events for the PC app."""
import copy
import json
import math
import threading
import time
from collections import deque
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from PIL import Image
from masks import render
from video_client import track_video
from video_tracking import WINDOW_FRAMES, decode_mask
from .configuration import Store, validate, public, text, DEFAULT
from .zone_rules import RuleState, evaluate


DATA = Path(__file__).resolve().parents[1]/'data'/'monitoring'


class Monitoring:
    def __init__(self, fetch, infer=track_video, path=DATA/'configuration.json'):
        self.fetch, self.infer = fetch, infer
        self.store = Store(path)
        self.config_error = None
        try:
            self.config = self.store.load()
        except ValueError as error:
            self.config = copy.deepcopy(DEFAULT)
            self.config_error = str(error)
        self.events_store = Store(Path(path).with_name('events.json'))
        self.events = deque(maxlen=100)
        if self.events_store.path.exists():
            try:
                saved = json.loads(self.events_store.path.read_text(encoding='utf-8'))
                if isinstance(saved, list):
                    self.events.extend(saved[-100:])
            except (ValueError, OSError):
                pass
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.thread = None
        self.running = self.connected = False
        self.revision = 0
        self.run_id = None
        self.rule = RuleState(self.config['rule']['persistence_seconds'])
        if self.config_error:
            self.rule.reason = self.config_error+' Use Save setup to replace it explicitly.'
        self.result = None
        self.result_at = None
        self.frames = deque(maxlen=8)
        self.output_id = 0
        self.last_frame = None

    def busy(self):
        return bool(self.thread and self.thread.is_alive())

    def event(self, kind, frame=None):
        entry = dict(id=str(uuid4()), time=datetime.now(timezone.utc).isoformat(), type=kind,
            state=self.rule.state, reason=self.rule.reason, run_id=self.run_id, revision=self.revision,
            camera_id=self.config['camera']['id'], prompt=self.config['sam_prompt'],
            zone=self.config['zone']['name'], action=self.config['rule']['action'],
            frame_sequence=frame.get('frame_sequence') if frame else None)
        self.events.append(entry)
        self.events_store.save(list(self.events))

    def save(self, data):
        with self.lock:
            if self.busy():
                raise ValueError('Stop monitoring before editing the camera, zone or rule.')
            config = validate(data, self.config)
            if config['camera']['url'] != self.config['camera']['url']:
                self.connected = False
                config['zone']['polygon'] = []
                config['zone']['frame_size'] = None
            self.store.save(config)
            self.config = config
            self.config_error = None
            self.result = self.result_at = None
            self.frames.clear()
            self.rule = RuleState(config['rule']['persistence_seconds'])
            return self.status()

    def connect(self, data):
        with self.lock:
            if self.busy():
                raise ValueError('Stop monitoring before connecting a camera.')
            if self.config_error:
                raise ValueError('Saved configuration is invalid. Review and Save setup before connecting.')
            config = validate({'camera':data.get('camera',{})}, self.config)
            changed_camera = config['camera']['url'] != self.config['camera']['url']
        jpeg, headers = self.fetch(config['camera'])
        self.freshness(headers)
        with Image.open(BytesIO(jpeg)) as image:
            size = list(image.size)
        with self.lock:
            if self.busy():
                raise ValueError('Monitoring started while connecting. Stop and retry.')
            if changed_camera or (config['zone']['frame_size'] and config['zone']['frame_size'] != size):
                config['zone'].update(polygon=[],frame_size=None)
            config['camera']['frame_size'] = size
            # Validate the server-observed dimensions before saving or rendering.
            config = validate(config, config)
            self.store.save(config)
            self.config, self.connected = config, True
            self.result = self.result_at = None
            self.last_frame = None
            self.rule = RuleState(config['rule']['persistence_seconds'])
            return self.status()

    @staticmethod
    def freshness(headers):
        sequence = headers.get('X-Frame-Sequence')
        age = float(headers.get('X-Frame-Age-Ms','nan'))
        if not isinstance(sequence,str) or not sequence.isdigit() or not math.isfinite(age) or not 0<=age<=2000:
            raise ValueError('Camera freshness metadata is unavailable or stale.')
        return sequence, age

    def snapshot(self):
        with self.lock:
            if not self.connected:
                raise ValueError('Connect the camera first.')
            camera = copy.deepcopy(self.config['camera'])
        try:
            jpeg, headers = self.fetch(camera)
            self.freshness(headers)
            return jpeg, headers
        except Exception:
            with self.lock:
                if self.rule.unavailable('Camera is disconnected or stale.') and self.running:
                    self.event('unavailable')
                self.result = self.result_at = None
            raise OSError('Camera unavailable. Check its address, service and credentials.') from None

    def start(self):
        with self.lock:
            if self.busy():
                raise ValueError('Monitoring is already active or finishing.')
            if not self.connected:
                raise ValueError('Connect the camera first.')
            self.config = validate(self.config,self.config,require_zone=True)
            self.cancel = threading.Event()
            self.run_id, self.revision = str(uuid4()), self.revision+1
            self.rule = RuleState(self.config['rule']['persistence_seconds'])
            self.result = self.result_at = None
            self.frames.clear()
            self.running = True
            self.event('started')
            self.thread = threading.Thread(target=self.loop,daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            self.cancel.set()
            if self.running:
                self.running = False
                self.rule.unavailable('Monitoring stopped.')
                self.result = self.result_at = None
                self.event('stopped')

    def change_prompt(self, prompt):
        prompt = text(prompt,'a detection target')
        with self.lock:
            if prompt == self.config['sam_prompt']:
                return
            config = copy.deepcopy(self.config)
            config['sam_prompt'] = prompt
            self.store.save(config)
            self.config = config
            self.revision += 1
            self.rule = RuleState(config['rule']['persistence_seconds'])
            self.rule.reason = 'Target changed. Waiting for fresh inference.'
            self.result = self.result_at = None
            self.frames.clear()
            self.event('prompt_changed')

    def publish(self, result, frame, revision, config):
        matched, details = evaluate(result,config)
        with Image.open(BytesIO(frame['jpeg'])) as image:
            annotated = render(image,[decode_mask(obj['mask']) for obj in result['objects']])
        with self.lock:
            if self.cancel.is_set() or revision != self.revision:
                return
            changed = self.rule.observe(matched,frame['captured_at'])
            self.output_id += 1
            row = {**result, 'output_id':self.output_id, 'run_id':self.run_id,
                   'zone_detections':details, 'condition_matched':matched, 'rule_state':self.rule.state,
                   '_captured_at':frame['captured_at']}
            self.frames.append(row)
            self.result, self.result_at = {**row, 'annotated_image':annotated}, frame['captured_at']
            if changed:
                kind = ('warning' if config['rule']['action']=='warning' else 'rule_triggered') if self.rule.state=='Warning' else 'cleared' if self.rule.state=='Normal' else 'unavailable'
                self.event(kind,result)

    def loop(self):
        previous = None
        while not self.cancel.is_set():
            with self.lock:
                config, revision = copy.deepcopy(self.config), self.revision
            stream = None
            try:
                frames = []
                began = time.monotonic()
                while len(frames)<WINDOW_FRAMES and not self.cancel.is_set():
                    if revision != self.revision:
                        break
                    requested = time.monotonic()
                    jpeg, headers = self.fetch(config['camera'])
                    sequence, age = self.freshness(headers)
                    if sequence != previous:
                        frames.append(dict(jpeg=jpeg,sequence=sequence,captured_at=requested-age/1000))
                        previous = sequence
                    if self.cancel.wait(0.25):
                        return
                    if time.monotonic()-began>3:
                        raise ValueError('Camera did not provide four fresh frames.')
                if self.cancel.is_set():
                    return
                if revision != self.revision:
                    continue
                stream = self.infer(frames,config['sam_prompt'],revision)
                for result in stream:
                    if self.cancel.is_set() or revision != self.revision:
                        break
                    index = result['frame_index']
                    if result['frame_sequence'] != frames[index]['sequence']:
                        raise ValueError('SAM result does not match its camera frame.')
                    self.publish(result,frames[index],revision,config)
            except Exception:
                with self.lock:
                    if not self.cancel.is_set() and revision == self.revision:
                        if self.rule.unavailable('Camera or SAM unavailable. Check the Pi connection and local GPU worker.'):
                            self.event('unavailable')
                        self.result = self.result_at = None
                self.cancel.wait(1)
            finally:
                if stream is not None:
                    stream.close()

    def frame_view(self, row):
        row = dict(row)
        age = time.monotonic()-row.pop('_captured_at')
        row.update(age_seconds=round(age,2),stale=age>self.rule.stale_seconds)
        return row

    def status(self):
        with self.lock:
            if self.running and self.rule.expire():
                self.event('unavailable')
            return dict(config=public(self.config), running=self.running, busy=self.busy(),
                connected=self.connected, run_id=self.run_id, revision=self.revision,
                state=self.rule.state, reason=self.rule.reason,
                warning_active=self.rule.state=='Warning' and self.config['rule']['action']=='warning',
                result=self.frame_view(self.result) if self.result else None,
                events=list(self.events), stale_seconds=self.rule.stale_seconds,
                capabilities={'camera':'Pi HTTP snapshots, optional HTTP Basic credentials',
                    'sam_selection':False, 'scada_output':False, 'id_scope':'four-frame SAM session'})

    def results(self, after):
        with self.lock:
            return dict(frames=[self.frame_view(row) for row in self.frames if row['output_id']>after],
                        latest_output_id=self.output_id,retention_frames=8)
