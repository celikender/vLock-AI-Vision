"""Experimental Pi snapshot -> local SAM -> presence events, on localhost:5053."""
import importlib.util
import json
import math
import logging
from io import BytesIO
from PIL import Image
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from uuid import uuid4

from backends import segment_photo
from event_prompt import interpret
from raised_hands import RaisedHands
from video_client import track_video
from video_tracking import WINDOW_FRAMES, validate_prompt, decode_mask
from masks import render, SegmentationError
PROMPT_LOCK = threading.Lock()

# Reuse the bounded original-JPEG LAN relay without moving experiment code.
spec = importlib.util.spec_from_file_location('camera_relay', Path(__file__).resolve().parents[2] / 'web/server.py')
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)


class Presence:
    """Two fresh observations confirm a transition; failures never imply absence."""
    def __init__(self, clock=time.monotonic, stale_seconds=10):
        self.clock = clock
        self.stale_seconds = stale_seconds
        self.state = 'unknown'
        self.reason = 'Waiting for fresh inference.'
        self.observed_at = None
        self.candidate = None
        self.hits = 0

    def unavailable(self, reason):
        changed = self.state != 'unknown'
        self.state, self.reason = 'unknown', reason
        self.candidate, self.hits = None, 0
        return changed

    def expire(self):
        if self.observed_at is not None and self.clock() - self.observed_at > self.stale_seconds:
            return self.unavailable('Observation is stale.')
        return False

    def observe(self, count, captured_at):
        if type(count) is not int or not 0 <= count <= 8:
            raise ValueError('Invalid local SAM object count.')
        if self.clock() - captured_at > self.stale_seconds:
            return self.unavailable('Inference finished on an old frame; waiting for a fresh result.')
        self.observed_at = captured_at
        candidate = 'present' if count else 'absent'
        self.hits = self.hits + 1 if candidate == self.candidate else 1
        self.candidate = candidate
        self.reason = f'{self.hits}/2 fresh observations confirming {candidate}.'
        if self.hits >= 2:
            changed = self.state != candidate
            self.state = candidate
            self.reason = 'Prompted object detected.' if count else 'No prompted object detected in sampled frames.'
            self.hits = 2
            return changed
        return False


class Monitor:
    def __init__(self, fetch=relay.snapshot, infer=segment_photo, video_infer=track_video):
        self.fetch, self.infer = fetch, infer
        self.video_infer = video_infer
        self.prompt_revision = 0
        self.video_results = deque(maxlen=8)
        self.output_id = 0
        self.raised_hands = RaisedHands()
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.thread = None
        self.running = False
        self.run_id = None
        self.address = self.prompt = ''
        self.presence = Presence()
        self.events = deque(maxlen=100)
        self.event_id = 0
        self.result = None
        self.sequence = None
        self.rule = 'presence'
        self.previous_hands = None

    def event(self, kind):
        self.event_id += 1
        if self.rule == 'two_hands_moving':
            kind = {'present':'two_hands_moving','absent':'no_two_hand_motion'}.get(kind, kind)
        elif self.rule == 'hands_above_head_moving':
            kind = {'present':'both_hands_raised_moving','absent':'raised_hand_motion_inactive'}.get(kind,kind)
        self.events.append(dict(id=self.event_id, run_id=self.run_id, type=kind, rule=self.rule,
            state=self.presence.state, reason=self.presence.reason, prompt=self.prompt,
            frame_sequence=self.sequence, experimental=True,
            time=datetime.now(timezone.utc).isoformat()))

    def start(self, address, prompt, rule='presence'):
        relay.camera_address(address)
        if rule not in ('presence', 'two_hands_moving', 'hands_above_head_moving', 'video_tracking'):
            raise ValueError('Select an experimental rule.')
        if rule == 'two_hands_moving':
            prompt = 'hand'
        elif rule == 'hands_above_head_moving':
            prompt = 'hand + head + person'
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 200:
            raise ValueError('Enter one object phrase (1–200 characters).')
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('Previous inference is still finishing. Wait before restarting.')
            self.address, self.prompt = address, prompt.strip()
            self.prompt_revision += 1
            self.video_results.clear()
            self.rule, self.previous_hands = rule, None
            self.run_id = str(uuid4())
            self.presence = Presence()
            self.raised_hands.reset()
            self.result = self.sequence = None
            self.cancel = threading.Event()
            self.running = True
            self.event('started')
            self.thread = threading.Thread(target=self.loop, daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            self.cancel.set()
            if self.running:
                self.running = False
                self.presence.unavailable('Monitoring stopped.')
                self.result = None
                self.event('stopped')

    def change_prompt(self, prompt):
        prompt = validate_prompt(prompt)
        with self.lock:
            if not self.running or self.rule != 'video_tracking':
                raise ValueError('Start video tracking before changing its prompt.')
            if prompt == self.prompt:
                return
            self.prompt = prompt
            self.prompt_revision += 1
            self.result = None
            self.video_results.clear()
            self.presence = Presence()
            self.presence.reason = 'Prompt changed; discarding old window and collecting fresh video.'
            self.event('prompt_changed')

    def frames_since(self, after):
        with self.lock:
            rows=[]
            for stored in self.video_results:
                if stored['output_id']>after:
                    row=dict(stored)
                    age=time.monotonic()-row.pop('_observed_at')
                    row.update(age_seconds=round(age,2),stale=age>self.presence.stale_seconds)
                    rows.append(row)
            return dict(frames=rows,
                latest_output_id=self.output_id,
                oldest_output_id=self.video_results[0]['output_id'] if self.video_results else None,
                prompt=self.prompt,prompt_revision=self.prompt_revision,running=self.running,
                retention_frames=8,experimental=True)

    def video_loop(self):
        """Collect a finite window only when ready; never queue the live preview."""
        previous = None
        while not self.cancel.is_set():
            with self.lock:
                prompt, revision = self.prompt, self.prompt_revision
            frames = []
            stream = None
            try:
                while len(frames)<WINDOW_FRAMES and not self.cancel.is_set():
                    with self.lock:
                        if revision != self.prompt_revision:
                            break
                    requested_at = time.monotonic()
                    jpeg, headers = self.fetch(self.address)
                    sequence = headers.get('X-Frame-Sequence')
                    age = float(headers.get('X-Frame-Age-Ms','nan'))
                    if not sequence or not math.isfinite(age) or not 0<=age<=2000:
                        raise ValueError('Camera freshness metadata is unavailable or stale.')
                    if sequence != previous:
                        frames.append(dict(jpeg=jpeg,sequence=sequence,captured_at=requested_at-age/1000))
                        previous = sequence
                    elif time.monotonic()-requested_at+age/1000>2:
                        raise ValueError('Camera repeated a stale frame.')
                    if self.cancel.wait(0.25):
                        return
                    if frames and time.monotonic()-frames[0]['captured_at']>3:
                        raise ValueError('Camera did not supply a fresh video window.')
                with self.lock:
                    if self.cancel.is_set():
                        return
                    if revision != self.prompt_revision:
                        continue
                stream = self.video_infer(frames,prompt,revision)
                for result in stream:
                    with self.lock:
                        if self.cancel.is_set() or revision != self.prompt_revision:
                            break
                    index = result['frame_index']
                    captured_at = frames[index]['captured_at']
                    with Image.open(BytesIO(frames[index]['jpeg'])) as image:
                        annotated = render(image,[decode_mask(obj['mask']) for obj in result['objects']])
                    with self.lock:
                        if self.cancel.is_set() or revision != self.prompt_revision:
                            break
                        self.sequence = result['frame_sequence']
                        self.output_id += 1
                        frame = {**result,'output_id':self.output_id,'run_id':self.run_id,
                            '_observed_at':captured_at,
                            'age_seconds':round(time.monotonic()-captured_at,2),
                            'stale':time.monotonic()-captured_at>self.presence.stale_seconds}
                        self.video_results.append(frame)
                        changed = self.presence.observe(result['count'],captured_at)
                        self.result = {**result,'annotated_image':annotated,'observation_started':captured_at}
                        if changed:
                            self.event(self.presence.state)
            except Exception as error:
                logging.getLogger('sam.video').exception('Camera video window failed')
                with self.lock:
                    if not self.cancel.is_set() and revision == self.prompt_revision:
                        changed = self.presence.unavailable(str(error))
                        self.result = None
                        if changed:
                            self.event('unknown')
                self.cancel.wait(1)
            finally:
                if stream is not None:
                    stream.close()

    def loop(self):
        if self.rule == 'video_tracking':
            self.video_loop()
            return
        previous = None
        while not self.cancel.is_set():
            try:
                requested_at = time.monotonic()
                jpeg, headers = self.fetch(self.address)
                sequence = headers.get('X-Frame-Sequence')
                age = float(headers.get('X-Frame-Age-Ms', 'nan'))
                if sequence is None or not math.isfinite(age) or not 0 <= age <= 2000:
                    raise ValueError('Camera frame freshness metadata is unavailable or stale.')
                if sequence == previous:
                    raise ValueError('Camera repeated a frame; waiting for a new observation.')
                previous = sequence
                captured_at = requested_at - age / 1000
                if self.cancel.is_set():
                    return
                if self.rule == 'hands_above_head_moving':
                    outputs = {}
                    for concept in ('hand','head','person'):
                        if self.cancel.is_set():
                            return
                        outputs[concept] = self.infer(jpeg, concept, 'local')
                    result = {**outputs['hand'],
                        'concepts':{name:value.get('detections',[]) for name,value in outputs.items()},
                        'elapsed_seconds':round(sum(value['elapsed_seconds'] for value in outputs.values()),2),
                        'peak_vram_mb':max(value['peak_vram_mb'] for value in outputs.values())}
                else:
                    result = self.infer(jpeg, self.prompt, 'local')
                with self.lock:
                    if self.cancel.is_set():
                        return
                    self.sequence = sequence
                    if self.presence.expire():
                        self.event('unknown')
                        self.previous_hands = None
                        self.raised_hands.reset()
                with self.lock:
                    if self.cancel.is_set():
                        return
                    count = result.get('count')
                    if type(count) is not int or not 0 <= count <= 8:
                        raise ValueError('Invalid object count.')
                    rule_reason = None
                    if self.rule == 'hands_above_head_moving':
                        if time.monotonic() - captured_at > self.presence.stale_seconds:
                            self.raised_hands.reset()
                            count, rule_reason = None, 'Multi-concept observation is stale; waiting for a fresh frame.'
                        else:
                            count, rule_reason = self.raised_hands.evaluate(result['concepts'])
                        if count is None:
                            changed = self.presence.unavailable(rule_reason)
                    elif self.rule == 'two_hands_moving':
                        detections = result.get('detections')
                        if not isinstance(detections, list):
                            raise ValueError('Restart the updated local worker for motion observations.')
                        hands = sorted(detections, key=lambda d:d['area'], reverse=True)[:2]
                        points = [d['center'] for d in hands]
                        previous_hands = self.previous_hands
                        self.previous_hands = points if len(points) == 2 else None
                        if time.monotonic() - captured_at > 10:
                            self.previous_hands = None
                        if len(points) == 2 and previous_hands is None:
                            changed = self.presence.unavailable('Two hands found; collecting a motion baseline.')
                            count = None
                        else:
                            count = int(two_hands_moved(previous_hands, points))
                    if count is not None:
                        changed = self.presence.observe(count, captured_at)
                        if rule_reason:
                            self.presence.reason = ('Confirmed: ' if self.presence.hits >= 2 else 'Confirming (1/2): ') + rule_reason
                        if self.rule == 'two_hands_moving' and self.presence.state != 'unknown':
                            self.presence.reason = ('Both hand masks moved across consecutive sampled frames.'
                                if self.presence.state == 'present' else 'Two-hand motion rule is inactive.')
                    self.result = {**result, 'frame_sequence': sequence,
                                   'observation_started': captured_at}
                    if changed:
                        self.event(self.presence.state)
            except Exception:
                with self.lock:
                    if self.cancel.is_set():
                        return
                    changed = self.presence.unavailable('Camera or inference unavailable. Check camera and selected model setup.')
                    self.previous_hands = None
                    self.raised_hands.reset()
                    self.result = None
                    if changed:
                        self.event('unknown')
            self.cancel.wait(0.25)

    def status(self):
        with self.lock:
            if self.running and self.presence.expire():
                self.event('unknown')
                self.raised_hands.reset()
            result = dict(self.result) if self.result else None
            if result:
                result['age_seconds'] = round(time.monotonic() - result.pop('observation_started'), 2)
            return dict(running=self.running, busy=bool(self.thread and self.thread.is_alive()),
                run_id=self.run_id, address=self.address, prompt=self.prompt, rule=self.rule,
                prompt_revision=self.prompt_revision,
                state=self.presence.state, reason=self.presence.reason,
                stale_seconds=self.presence.stale_seconds,
                result=result, events=list(self.events), experimental=True)


def two_hands_moved(previous, current, threshold=0.04):
    """Nearest pairing of two normalized mask centers; both must move 4% of frame."""
    if previous is None or len(current) != 2:
        return False
    pairings = ([math.dist(previous[0], current[0]), math.dist(previous[1], current[1])],
                [math.dist(previous[0], current[1]), math.dist(previous[1], current[0])])
    distances = min(pairings, key=sum)
    return all(threshold <= distance <= 0.5 for distance in distances)


monitor = Monitor()


class Handler(relay.Handler):
    def reply(self, code, body, mime, headers):
        try:
            super().reply(code, body, mime, headers)
        except ConnectionAbortedError:
            pass

    def allowed(self, mutation=False):
        host = self.headers.get('Host')
        origin = self.headers.get('Origin')
        return host in ('localhost:5053', '127.0.0.1:5053') and (
            origin == 'http://' + host if mutation or origin else True)

    def send_json(self, code, data):
        self.reply(code, json.dumps(data).encode(), 'application/json', {})

    def do_GET(self):
        self.connection.settimeout(5)
        if not self.allowed():
            return self.send_json(403, {'error': 'Use the local experiment page.'})
        url = urlsplit(self.path)
        if url.path == '/':
            self.reply(200, Path(__file__).with_name('monitor.html').read_bytes(), 'text/html; charset=utf-8', {})
        elif url.path == '/api/status':
            self.send_json(200, monitor.status())
        elif url.path == '/api/video/results':
            try:
                after = int(parse_qs(url.query).get('after',['0'])[0])
                self.send_json(200, monitor.frames_since(after))
            except ValueError:
                self.send_json(400, {'error':'Use a numeric output cursor.'})
        elif url.path == '/api/snapshot':
            try:
                body, headers = relay.snapshot(parse_qs(url.query).get('address', [''])[0])
                self.reply(200, body, 'image/jpeg', headers)
            except Exception:
                self.send_json(502, {'error': 'Camera unavailable.'})
        else:
            self.send_json(404, {'error': 'Not found.'})

    def do_POST(self):
        self.connection.settimeout(5)
        if not self.allowed(mutation=True):
            return self.send_json(403, {'error': 'Use the local experiment page.'})
        if self.path not in ('/api/start', '/api/stop', '/api/interpret', '/api/prompt'):
            return self.send_json(404, {'error': 'Not found.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if self.headers.get('Content-Type') != 'application/json' or not 0 < length <= 4096:
                raise ValueError('Use a small JSON configuration.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Invalid configuration.')
            if self.path == '/api/interpret':
                if not PROMPT_LOCK.acquire(blocking=False):
                    return self.send_json(409, {'error':'An interpretation is already running.'})
                try:
                    return self.send_json(200, interpret(data.get('text')))
                except ValueError as error:
                    return self.send_json(400, {'error':str(error)})
                finally:
                    PROMPT_LOCK.release()
            elif self.path == '/api/start':
                monitor.start(data.get('address', ''), data.get('prompt', ''), data.get('rule', 'presence'))
            elif self.path == '/api/prompt':
                monitor.change_prompt(data.get('prompt'))
            else:
                monitor.stop()
            self.send_json(200, monitor.status())
        except (ValueError, TypeError, AttributeError, SegmentationError):
            self.send_json(400, {'error': 'Check the LAN IP and object phrase; wait if a previous inference is finishing.'})


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 5053), Handler)
    server.daemon_threads = True
    print('Open http://localhost:5053 — experimental local presence events', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop()
        server.server_close()
