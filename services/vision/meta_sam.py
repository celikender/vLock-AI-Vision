"""SAM 3.1 through the Meta Model API, as an alternative to the local GPU worker.

Selected with VLOCK_SAM_BACKEND=meta_api (one image per check) or meta_api_video (a four-frame
clip per check). Both return the same rows as transport.track_video, so rules, tags and adapters
do not change. Every request is paid and its frames leave this PC. A timeout, error or unreadable answer raises, which the monitor reports
as Unknown, never Clear; there are no retries.
"""
import base64
import csv
import json
import math
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
from meta_sam_parser import CompletedOutcome, decode_mask_to_raster, image_segmentation_format, video_segmentation_format
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from .assistant import settings
from .masks import ExplainedError, MAX_OBJECTS, SegmentationError, TooManyObjects, outline
from .video import MAX_JPEG_BYTES, decode_mask, encode_mask, validate_prompt

DEFAULT_TIMEOUT_MS = 3000
DEFAULT_DAILY_LIMIT = 10.0
ACCESS_WAIT = 60
MAX_WAIT = 30
# Statuses that may have been billed. Refused or unreachable requests are not counted.
BILLABLE = ('ok', 'late', 'timeout', 'error', 'too_many')
MIN_VIDEO_TIMEOUT = 6.0
VIDEO_FPS = 4
# Measured: 6 objects on each of 4 frames confirm in 6.2 s, and 8 outlast the freshness limit.
VIDEO_MAX_OBJECTS = 6
PRICE_PER_IMAGE = 2.50/1000
MAX_OUTPUT = 16*1024*1024
LOG_LIMIT = 5*1024*1024
LOG_COLUMNS = ['timestamp_utc', 'backend', 'phrase', 'sam_ms', 'matches', 'top_score', 'status']
STATUS_MESSAGES = {401: 'Meta rejected the API key. Check it on the Setup page.',
                   402: 'Meta billing is not configured for this key.',
                   403: 'This Meta key cannot use SAM 3.1.', 404: 'This Meta key cannot use SAM 3.1.',
                   429: 'Meta rate limit or quota reached.'}


def daily_limit(values):
    """The daily spending limit in USD; anything unusable falls back to the default, never to no limit."""
    try:
        limit = float(values.get('VLOCK_SAM_DAILY_LIMIT_USD') or DEFAULT_DAILY_LIMIT)
    except ValueError:
        return DEFAULT_DAILY_LIMIT
    return limit if math.isfinite(limit) and limit > 0 else DEFAULT_DAILY_LIMIT


def utc_day():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def meta_client(key, base_url, timeout):
    return OpenAI(api_key=key, base_url=base_url, timeout=timeout, max_retries=0)


def frame_size(jpeg):
    if len(jpeg) > MAX_JPEG_BYTES:
        raise SegmentationError('Camera frame is too large for Meta SAM.', 400)
    try:
        with Image.open(BytesIO(jpeg)) as image:
            if image.format != 'JPEG':
                raise ValueError()
            return image.size
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise SegmentationError('Meta SAM needs a readable camera JPEG.', 400) from None


def mask_records(text, output_format):
    if len(text) > MAX_OUTPUT:
        raise SegmentationError('Meta segmentation output is too large.')
    parser = output_format.create_parser()
    parser.push(text)
    result = parser.finish(CompletedOutcome()).result
    if any(item.severity == 'error' for item in result.diagnostics):
        raise SegmentationError('Meta returned malformed segmentation data.')
    records = [record for record in result.records if record.kind == 'mask']
    if text.strip() and not records:
        raise SegmentationError('Meta returned text without usable masks.')
    return records


def object_row(record, width, height):
    """One Meta mask record to the local worker's object row, with a full-frame mask."""
    left, top, right, bottom = (int(value) for value in (record.bounds.left, record.bounds.top,
                                                         record.bounds.right, record.bounds.bottom))
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise SegmentationError('Meta mask bounds do not match the camera frame.')
    score = record.confidence
    if score is not None and not math.isfinite(score):
        raise SegmentationError('Meta returned a nonfinite score.')
    raster = bytes(decode_mask_to_raster(record.mask))
    patch = Image.frombytes('L', (record.mask.width, record.mask.height), raster).point(lambda v: 255 if v else 0)
    if patch.size != (right-left, bottom-top):
        patch = patch.resize((right-left, bottom-top), Image.Resampling.NEAREST)
    mask = Image.new('L', (width, height))
    mask.paste(patch, (left, top))
    return {'object_id': int(record.object_id), 'track_id': f'meta:{record.object_id}',
            'bbox_xywh': [left/width, top/height, (right-left)/width, (bottom-top)/height],
            'score': score, 'mask': encode_mask(mask)}


def parse_objects(text, width, height):
    """An image answer: the object rows of its one frame."""
    # Counted before parsing, which takes about 0.1 s per mask.
    if text.count('<|mask') > MAX_OBJECTS:
        raise TooManyObjects()
    records = mask_records(text, image_segmentation_format())
    return [object_row(record, width, height) for record in records]


def parse_video(text, width, height, frame_count):
    """A video answer: object rows per frame. A frame with no objects has no line and an empty list."""
    if text.count('<|mask') > VIDEO_MAX_OBJECTS*frame_count:
        raise TooManyObjects(VIDEO_MAX_OBJECTS)
    records = mask_records(text, video_segmentation_format())
    frames = [[] for _ in range(frame_count)]
    for record in records:
        index = record.frame.frame_index
        if not 0 <= index < frame_count:
            raise SegmentationError('Meta returned a frame outside the camera window.')
        frames[index].append(object_row(record, width, height))
    return frames


def encode_window(frames):
    """Camera JPEGs to one short MP4, the form the Meta video request accepts. Returns (mp4, width, height)."""
    images = [cv2.imdecode(np.frombuffer(frame['jpeg'], np.uint8), cv2.IMREAD_COLOR) for frame in frames]
    if any(image is None for image in images) or len({image.shape for image in images}) != 1:
        raise SegmentationError('Meta SAM needs readable camera JPEGs of one size.', 400)
    height, width = images[0].shape[:2]
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)/'window.mp4'
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), VIDEO_FPS, (width, height))
        if not writer.isOpened():
            raise SegmentationError('Could not prepare the camera video for Meta SAM.')
        for image in images:
            writer.write(image)
        writer.release()
        data = path.read_bytes()
    if not data:
        raise SegmentationError('Could not prepare the camera video for Meta SAM.')
    return data, width, height


class MetaSam:
    """Inference callable for Monitoring, plus the status methods the app expects of its SAM worker."""
    backend_name = 'meta_api'
    window_frames = 1
    min_check_seconds = 1.0
    price_per_request = PRICE_PER_IMAGE
    unavailable_reason = 'Meta SAM unavailable. Check the internet connection and the API key.'
    start_message = 'SAM 3.1: Meta Model API. Camera frames are sent to Meta and each request is billed.'

    def __init__(self, log_path, config=settings, client_factory=meta_client, clock=time.monotonic, today=utc_day):
        self.log_path = Path(log_path)
        self.usage_path = self.log_path.with_name('sam_usage.json')
        self.config, self.client_factory, self.clock, self.today = config, client_factory, clock, today
        self.lock = threading.Lock()
        self.client = self.client_key = None
        self.calls = deque()
        self.last_status = None
        self.failures, self.blocked_until, self.blocked_reason = 0, 0, ''
        self.usage = self.load_usage()

    def load_usage(self):
        """Kept in a file so that a restart cannot reset the daily limit."""
        try:
            usage = json.loads(self.usage_path.read_text(encoding='utf-8'))
            return dict(day=str(usage['day']), spend=float(usage['spend']))
        except (OSError, ValueError, KeyError, TypeError):
            return dict(day=self.today(), spend=0.0)

    def spend_today(self):
        if self.usage['day'] != self.today():
            self.usage = dict(day=self.today(), spend=0.0)
        return self.usage['spend']

    def add_spend(self):
        self.usage = dict(day=self.today(), spend=self.spend_today()+self.price_per_request)
        temporary = self.usage_path.with_name(self.usage_path.name+'.tmp')
        try:
            self.usage_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(self.usage), encoding='utf-8')
            temporary.replace(self.usage_path)
        except OSError:
            pass  # The limit still holds in memory for this run.

    def check_allowed(self, values):
        """Stop before paying: over the daily limit, or waiting after repeated failures."""
        with self.lock:
            limit = daily_limit(values)
            if self.spend_today()+self.price_per_request > limit:
                raise ExplainedError(f'Meta SAM daily spending limit of ${limit:.2f} reached. '
                                     'Raise it on the Setup page, or wait until midnight UTC.', 429)
            if self.clock() < self.blocked_until:
                raise ExplainedError(self.blocked_reason, 503)

    def note_outcome(self, status, reason):
        """Back off after failures: a refused key waits longest, and other errors wait longer each time."""
        if status in ('ok', 'too_many'):
            self.failures, self.blocked_until = 0, 0
        elif status.startswith('http_') and int(status[5:]) in STATUS_MESSAGES:
            self.blocked_until, self.blocked_reason = self.clock()+ACCESS_WAIT, reason
        else:
            self.failures += 1
            if self.failures >= 2:
                self.blocked_until = self.clock()+min(MAX_WAIT, 2**(self.failures-1))
                self.blocked_reason = self.unavailable_reason

    def connection(self, values):
        """One kept-alive client: a new TLS connection for every frame would add latency."""
        key = (values.get('META_API_KEY') or values.get('MODEL_API_KEY') or '').strip()
        if not key:
            raise ExplainedError('Add your Meta API key on the Setup page to use Meta SAM.', 503)
        timeout = self.timeout_seconds(values)
        with self.lock:
            if self.client is None or self.client_key != (key, timeout):
                if self.client is not None:
                    self.client.close()
                self.client = self.client_factory(key, values.get('META_BASE_URL') or 'https://api.meta.ai/v1', timeout)
                # A new key or limit gets a fresh start instead of waiting out the old failure.
                self.failures, self.blocked_until = 0, 0
                self.client_key = (key, timeout)
            return self.client, timeout

    @staticmethod
    def timeout_seconds(values):
        try:
            milliseconds = int(values.get('VLOCK_SAM_TIMEOUT_MS') or DEFAULT_TIMEOUT_MS)
        except ValueError:
            milliseconds = DEFAULT_TIMEOUT_MS
        return (milliseconds if milliseconds > 0 else DEFAULT_TIMEOUT_MS)/1000

    def segment(self, jpeg, prompt):
        """One request for one frame and one phrase. Returns (objects, width, height)."""
        width, height = frame_size(jpeg)
        image = {'type': 'input_image', 'image_url': 'data:image/jpeg;base64,'+base64.b64encode(jpeg).decode('ascii')}
        return self.request(prompt, image, lambda text: parse_objects(text, width, height), lambda objects: objects), width, height

    def request(self, prompt, media, parse, flatten):
        """One paid request with no retry. Any failure raises; the caller's monitor reports Unknown."""
        values = self.config()
        client, timeout = self.connection(values)
        self.check_allowed(values)
        began = self.clock()
        status, objects, reason = 'error', [], ''
        try:
            response = client.responses.create(
                model=values.get('META_SAM_MODEL') or 'sam-3.1',
                input=[{'role': 'user', 'content': [{'type': 'input_text', 'text': prompt}, media]}],
                metadata={'mask_encoding': 'one_bit', 'include_confidence': 'true'})
            # The client's timeout covers each network step; this one covers the whole answer.
            if self.clock()-began > timeout:
                status = 'late'
                raise SegmentationError('Meta SAM answered after the timeout.', 504)
            if response.status != 'completed':
                raise SegmentationError('Meta returned an incomplete segmentation.')
            parsed = parse(response.output_text or '')
            objects = flatten(parsed)
            status = 'ok'
            return parsed
        except APITimeoutError:
            status = 'timeout'
            raise SegmentationError('Meta SAM timed out.', 504) from None
        except APIConnectionError:
            status = 'connection'
            raise SegmentationError('Cannot reach Meta. Check the internet connection.', 503) from None
        except APIStatusError as error:
            status = f'http_{error.status_code}'
            reason = STATUS_MESSAGES.get(error.status_code)
            if reason:
                raise ExplainedError(reason, error.status_code) from None
            raise SegmentationError('Meta rejected the SAM request.', error.status_code) from None
        except TooManyObjects:
            status = 'too_many'
            raise
        except SegmentationError:
            raise
        except Exception:
            raise SegmentationError('Meta SAM request failed.') from None
        finally:
            self.record(prompt, (self.clock()-began)*1000, objects, status, reason)

    def record(self, phrase, milliseconds, objects, status, reason=''):
        scores = [obj['score'] for obj in objects if obj['score'] is not None]
        with self.lock:
            now = self.clock()
            self.calls.append(now)
            self.last_status = status
            self.note_outcome(status, reason)
            if status in BILLABLE:
                self.add_spend()
            while self.calls and now-self.calls[0] > 3600:
                self.calls.popleft()
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                if self.log_path.exists() and self.log_path.stat().st_size >= LOG_LIMIT:
                    self.log_path.replace(self.log_path.with_name(self.log_path.name+'.1'))
                new = not self.log_path.exists()
                with self.log_path.open('a', newline='', encoding='utf-8') as handle:
                    writer = csv.writer(handle)
                    if new:
                        writer.writerow(LOG_COLUMNS)
                    writer.writerow([datetime.now(timezone.utc).isoformat(timespec='milliseconds'), self.backend_name, phrase,
                                     round(milliseconds), len(objects), round(max(scores), 4) if scores else '', status])
            except OSError:
                pass  # A locked log never changes a result.

    def __call__(self, frames, prompt, revision):
        prompt = validate_prompt(prompt)
        for index, frame in enumerate(frames):
            objects, width, height = self.segment(frame['jpeg'], prompt)
            yield dict(type='frame', session_id='meta', prompt=prompt, prompt_revision=revision,
                       frame_index=index, frame_sequence=frame['sequence'], width=width, height=height,
                       box_coordinates='normalized_xywh', objects=objects, count=len(objects),
                       id_scope='frame', window_frames=len(frames))

    def segment_regions(self, jpeg, prompt):
        """Outline each match of one phrase on one frame, for area proposals."""
        regions = []
        for obj in self.segment(jpeg, validate_prompt(prompt))[0]:
            mask = decode_mask(obj['mask'])
            area = mask.histogram()[255]/(mask.width*mask.height)
            polygon = outline(mask) if area > 0 else None
            if polygon:
                regions.append(dict(polygon=polygon, area=round(area, 4)))
        regions.sort(key=lambda region: region['area'], reverse=True)
        return regions

    def status(self):
        """Ready means a key is set. Whether Meta answers shows in the zone's result, not here."""
        values = self.config()
        if not (values.get('META_API_KEY') or values.get('MODEL_API_KEY') or '').strip():
            return dict(state='failed', message='Add META_API_KEY on the Setup page to use Meta SAM.',
                        owned=False, backend=self.backend_name)
        with self.lock:
            now = self.clock()
            calls = sum(1 for moment in self.calls if now-moment <= 3600)
            last = self.last_status
            spend, limit = self.spend_today(), daily_limit(values)
        return dict(state='ready', owned=False, backend=self.backend_name, calls_last_hour=calls,
                    last_request=None if last is None else 'ok' if last == 'ok' else 'failing',
                    spend_today=round(spend, 4), spend_limit=limit, limit_reached=spend+self.price_per_request > limit,
                    message=f'SAM 3.1 through the Meta Model API. Estimated ${spend:.2f} today of a ${limit:.2f} limit. '
                            f'{calls} requests in the last hour. Your Meta account shows the real bill.')

    def start(self):
        pass

    def restart(self):
        return self.status()

    def stop(self, wait=False):
        with self.lock:
            if self.client is not None:
                self.client.close()
            self.client = self.client_key = None


class MetaSamVideo(MetaSam):
    """One video request per object over a four-frame camera window, tracking like the local worker.

    Each request is billed for Meta's minimum of 50 frames, so about $0.01 however short the clip is.
    """
    backend_name = 'meta_api_video'
    window_frames = 4
    min_check_seconds = 0
    price_per_request = 0.20/1000*50
    start_message = ('SAM 3.1: Meta Model API, video. Camera frames are sent to Meta and each request is billed '
                     'for at least 50 frames.')

    @staticmethod
    def timeout_seconds(values):
        # Measured at 1.6-2.9 s per request: an image limit would fail healthy requests.
        return max(MetaSam.timeout_seconds(values), MIN_VIDEO_TIMEOUT)

    def __call__(self, frames, prompt, revision):
        prompt = validate_prompt(prompt)
        data, width, height = encode_window(frames)
        video = {'type': 'input_video', 'video_url': 'data:video/mp4;base64,'+base64.b64encode(data).decode('ascii')}
        rows = self.request(prompt, video, lambda text: parse_video(text, width, height, len(frames)),
                            lambda parsed: max(parsed, key=len))
        for index, (frame, objects) in enumerate(zip(frames, rows)):
            yield dict(type='frame', session_id='meta', prompt=prompt, prompt_revision=revision,
                       frame_index=index, frame_sequence=frame['sequence'], width=width, height=height,
                       box_coordinates='normalized_xywh', objects=objects, count=len(objects),
                       id_scope='session', window_frames=len(frames))
