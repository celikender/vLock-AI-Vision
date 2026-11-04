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
from .masks import TooManyObjects, render
from .transport import track_video
from .video import WINDOW_FRAMES, decode_mask
from .configuration import Store, validate, public, text, DEFAULT
from .zone_rules import RuleState, evaluate_all, targets
from .output import UnwiredOutput


DATA = Path(__file__).resolve().parents[2]/'data'/'application'/'default_monitor'


class Monitoring:
    def __init__(self, fetch, infer=track_video, path=DATA/'configuration.json', publisher=None, event_limit=100):
        self.fetch, self.infer = fetch, infer
        self.store = Store(path)
        self.config_error = None
        try:
            self.config = self.store.load()
        except ValueError as error:
            self.config = copy.deepcopy(DEFAULT)
            self.config_error = str(error)
        self.events_store = Store(Path(path).with_name('events.json'))
        self.events = deque(maxlen=event_limit)
        if self.events_store.path.exists():
            try:
                saved = json.loads(self.events_store.path.read_text(encoding='utf-8'))
                if isinstance(saved, list):
                    self.events.extend(saved[-event_limit:])
            except (ValueError, OSError):
                pass
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.thread = None
        self.running = self.connected = False
        self.revision = 0
        self.run_id = None
        self.rule = RuleState(self.config['rule']['persistence_seconds'],stale_seconds=self.config.get('validity_seconds',10))
        if self.config_error:
            self.rule.reason = self.config_error+' Use Save setup to replace it explicitly.'
        self.result = None
        self.result_at = None
        self.frames = deque(maxlen=8)
        self.output_id = 0
        self.last_frame = None
        self.bridge = publisher or UnwiredOutput()
        self.storage_error = None

    def bridge_unknown(self):
        self.bridge.send(self.config, 'Unknown', self.rule.reason)

    @property
    def window_frames(self):
        return getattr(self.infer,'window_frames',WINDOW_FRAMES)

    def busy(self):
        return bool(self.thread and self.thread.is_alive())

    def event(self, kind, frame=None):
        entry = dict(id=str(uuid4()), time=datetime.now(timezone.utc).isoformat(), type=kind,
            state=self.rule.state, reason=self.rule.reason, run_id=self.run_id, revision=self.revision,
            camera_id=self.config['camera']['id'], prompt=self.config['sam_prompt'],
            zone=self.config['zone']['name'], action=self.config['rule']['action'],
            frame_sequence=frame.get('frame_sequence') if frame else None)
        self.events.append(entry)
        try:
            self.events_store.save(list(self.events))
            self.storage_error = None
        except OSError:
            # A full disk or a locked file must not stop monitoring or the status API.
            self.storage_error = 'Event history could not be saved (disk full or file locked); events are kept in memory.'

    def save(self, data):
        with self.lock:
            if self.busy():
                raise ValueError('Stop monitoring before editing the camera, zone or rule.')
            config = validate(data, self.config)
            if self.config.get('bridge', {}).get('enabled'):
                self.rule.unavailable('Monitoring configuration changed.')
                self.bridge_unknown()
            if config['camera']['url'] != self.config['camera']['url']:
                self.connected = False
                config['zone']['polygon'] = []
                config['zone']['frame_size'] = None
            self.store.save(config)
            self.config = config
            self.config_error = None
            self.result = self.result_at = None
            self.frames.clear()
            self.rule = RuleState(config['rule']['persistence_seconds'],stale_seconds=config.get('validity_seconds',10))
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
            self.rule = RuleState(config['rule']['persistence_seconds'],stale_seconds=config.get('validity_seconds',10))
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
                    self.bridge_unknown()
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
            self.rule = RuleState(self.config['rule']['persistence_seconds'],stale_seconds=self.config.get('validity_seconds',10))
            self.result = self.result_at = None
            self.frames.clear()
            self.running = True
            self.event('started')
            self.bridge_unknown()
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
                self.bridge_unknown()

    def change_prompt(self, prompt):
        prompt = text(prompt,'a detection target')
        with self.lock:
            if self.config.get('bridge', {}).get('enabled') and prompt.lower() != 'person':
                raise ValueError('Stop and disable bridge publishing before changing the person target.')
            if prompt == self.config['sam_prompt']:
                return
            config = copy.deepcopy(self.config)
            config['sam_prompt'] = prompt
            self.store.save(config)
            self.config = config
            self.revision += 1
            self.rule = RuleState(config['rule']['persistence_seconds'],stale_seconds=config.get('validity_seconds',10))
            self.rule.reason = 'Target changed. Waiting for fresh inference.'
            self.result = self.result_at = None
            self.frames.clear()
            self.event('prompt_changed')
            self.bridge_unknown()

    def publish(self, result, frame, revision, config, render_overlay=True, check_seconds=None):
        results = result if isinstance(result, list) else [result]
        matched, details, outcomes = evaluate_all(results, config)
        names = [prompt for prompt, _ in targets(config)]
        objects = ([dict(obj, concept=name) for name, r in zip(names, results) for obj in r['objects']]
                   if len(results) > 1 else results[0]['objects'])
        counts = {name: r['count'] for name, r in zip(names, results)}
        # Highest SAM score per object for SCADA diagnostics; never used for the rule.
        scores = {name: max((o['score'] for o in r['objects'] if isinstance(o.get('score'), (int, float))
                             and not isinstance(o.get('score'), bool)), default=None) for name, r in zip(names, results)}
        result = {**results[0], 'objects': objects, 'count': len(objects), 'counts': counts,
                  'object_matches': dict(zip(names, outcomes)), 'check_seconds': check_seconds}
        if render_overlay:
            with Image.open(BytesIO(frame['jpeg'])) as image:
                annotated = render(image,[decode_mask(obj['mask']) for obj in objects])
        with self.lock:
            if self.cancel.is_set() or revision != self.revision:
                return
            changed = self.rule.observe(matched,frame['captured_at'])
            self.output_id += 1
            row = {**result, 'output_id':self.output_id, 'run_id':self.run_id,
                   'zone_detections':details, 'condition_matched':matched, 'rule_state':self.rule.state,
                   '_captured_at':frame['captured_at']}
            self.frames.append(row)
            # Keep geometry, persistence and events for every frame. Only the newest
            # frame in a window replaces the UI image and its matching metadata.
            if render_overlay:
                self.result, self.result_at = {**row, 'annotated_image':annotated}, frame['captured_at']
            if changed:
                kind = ('warning' if config['rule']['action']=='warning' else 'rule_triggered') if self.rule.state=='Warning' else 'cleared' if self.rule.state=='Normal' else 'unavailable'
                self.event(kind,result)
            if changed or render_overlay:
                self.bridge.send(config, self.rule.state, self.rule.reason, frame['captured_at'],
                                 counts if len(counts) > 1 else result['count'],
                                 {'run_id': self.run_id, 'frame_sequence': result['frame_sequence'],
                                  'condition_matched': matched, 'counts': counts, 'scores': scores,
                                  'check_seconds': check_seconds})

    def loop(self):
        """Monitoring thread. Any unexpected failure ends in Unknown with a reason, never a silent stop."""
        try:
            self._loop()
        except Exception:
            self.lost('Monitoring stopped unexpectedly. Enable monitoring again; see the application log if it repeats.')

    def lost(self, reason):
        """Mark a monitor whose thread is gone: Unknown everywhere, stopped, with the reason."""
        with self.lock:
            if not self.running:
                return False
            self.running = False
            self.cancel.set()
            self.rule.unavailable(reason)
            self.result = self.result_at = None
            try:
                self.event('stopped')
                self.bridge_unknown()
            except Exception:
                pass
            return True

    def check_alive(self):
        """Watchdog: a running monitor whose thread died is reported, not left looking active."""
        if self.running and self.thread is not None and not self.thread.is_alive():
            return self.lost('Monitoring stopped unexpectedly. Enable monitoring again; see the application log if it repeats.')
        return False

    def _loop(self):
        previous = None
        while not self.cancel.is_set():
            with self.lock:
                config, revision = copy.deepcopy(self.config), self.revision
            stream = None
            camera_stage = True
            try:
                frames = []
                began = time.monotonic()
                window = self.window_frames
                while len(frames)<window and not self.cancel.is_set():
                    if revision != self.revision:
                        break
                    requested = time.monotonic()
                    jpeg, headers = self.fetch(config['camera'])
                    sequence, age = self.freshness(headers)
                    if sequence != previous:
                        frames.append(dict(jpeg=jpeg,sequence=sequence,captured_at=requested-age/1000))
                        previous = sequence
                    if len(frames)<window and self.cancel.wait(0.25):
                        return
                    if time.monotonic()-began>3:
                        raise ValueError('Camera did not provide enough fresh frames.')
                if self.cancel.is_set():
                    return
                if revision != self.revision:
                    continue
                # One SAM pass per object over the same frames, one after another on the
                # loaded worker; publish only when every object has every frame.
                camera_stage = False
                began_check = time.monotonic()
                collected = []
                for prompt, _ in targets(config):
                    rows = {}
                    stream = self.infer(frames,prompt,revision)
                    for result in stream:
                        if self.cancel.is_set() or revision != self.revision:
                            break
                        index = result['frame_index']
                        if result['frame_sequence'] != frames[index]['sequence']:
                            raise ValueError('SAM result does not match its camera frame.')
                        rows[index] = result
                    stream.close()
                    stream = None
                    if self.cancel.is_set() or revision != self.revision:
                        break
                    if set(rows) != set(range(len(frames))):
                        raise ValueError('SAM did not return every frame for one object.')
                    collected.append(rows)
                else:
                    check_seconds = round(time.monotonic()-began_check, 2)
                    for index in range(len(frames)):
                        self.publish([rows[index] for rows in collected],frames[index],revision,config,
                                     render_overlay=index==len(frames)-1,check_seconds=check_seconds)
                    # A paid backend sets a pace; the local worker runs flat out.
                    pause = getattr(self.infer,'min_check_seconds',0)-(time.monotonic()-began)
                    if pause>0 and self.cancel.wait(pause):
                        return
            except Exception as error:
                with self.lock:
                    if not self.cancel.is_set() and revision == self.revision:
                        if self.rule.unavailable(str(error) if isinstance(error,TooManyObjects) else
                                'Camera unavailable. Check the camera connection.' if camera_stage else
                                getattr(self.infer,'unavailable_reason','Local SAM unavailable. Check the GPU worker.')):
                            self.event('unavailable')
                        self.result = self.result_at = None
                        self.bridge_unknown()
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
                self.bridge_unknown()
            return dict(config=public(self.config), running=self.running, busy=self.busy(), storage_error=self.storage_error,
                connected=self.connected, run_id=self.run_id, revision=self.revision,
                state=self.rule.state, reason=self.rule.reason,
                warning_active=self.rule.state=='Warning' and self.config['rule']['action']=='warning',
                result=self.frame_view(self.result) if self.result else None,
                events=list(self.events), stale_seconds=self.rule.stale_seconds,
                bridge_output=dict(self.bridge.status, enabled=self.config.get('bridge', {}).get('enabled', False)),
                capabilities={'camera':'Pi HTTP snapshots',
                    'sam_selection':False, 'scada_output':True, 'machine_commands':False,
                    'id_scope':f'{self.window_frames}-frame SAM check'})

    def results(self, after):
        with self.lock:
            return dict(frames=[self.frame_view(row) for row in self.frames if row['output_id']>after],
                        latest_output_id=self.output_id,retention_frames=8)
