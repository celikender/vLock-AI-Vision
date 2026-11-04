"""SAM 3.1 through the Meta Model API, as an alternative to the local GPU worker.

Selected with VLOCK_SAM_BACKEND=meta_api. It returns the same rows as transport.track_video,
so rules, tags and adapters do not change. Each frame and phrase is one paid request and the
frame leaves this PC. A timeout, error or unreadable answer raises, which the monitor reports
as Unknown, never Clear; there are no retries.
"""
import base64
import csv
import math
import threading
import time
from collections import deque
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from meta_sam_parser import CompletedOutcome, decode_mask_to_raster, image_segmentation_format
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from .assistant import settings
from .masks import SegmentationError, outline
from .video import MAX_JPEG_BYTES, decode_mask, encode_mask, validate_prompt

DEFAULT_TIMEOUT_MS = 3000
PRICE_PER_IMAGE = 2.50/1000
MAX_OUTPUT = 16*1024*1024
MAX_OBJECTS = 32
LOG_LIMIT = 5*1024*1024
LOG_COLUMNS = ['timestamp_utc', 'backend', 'phrase', 'sam_ms', 'matches', 'top_score', 'status']
STATUS_MESSAGES = {401: 'Meta rejected the API key. Check META_API_KEY in .env.',
                   402: 'Meta billing is not configured for this key.',
                   403: 'This Meta key cannot use SAM 3.1.', 404: 'This Meta key cannot use SAM 3.1.',
                   429: 'Meta rate limit or quota reached.'}


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


def parse_objects(text, width, height):
    """Meta's segmentation text to the local worker's object rows, with full-frame masks."""
    if len(text) > MAX_OUTPUT:
        raise SegmentationError('Meta segmentation output is too large.')
    parser = image_segmentation_format().create_parser()
    parser.push(text)
    result = parser.finish(CompletedOutcome()).result
    if any(item.severity == 'error' for item in result.diagnostics):
        raise SegmentationError('Meta returned malformed segmentation data.')
    records = [record for record in result.records if record.kind == 'mask']
    if text.strip() and not records:
        raise SegmentationError('Meta returned text without usable masks.')
    if len(records) > MAX_OBJECTS:
        raise SegmentationError('Too many objects. Narrow the phrase.')
    objects = []
    for record in records:
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
        objects.append({'object_id': int(record.object_id), 'track_id': f'meta:{record.object_id}',
                        'bbox_xywh': [left/width, top/height, (right-left)/width, (bottom-top)/height],
                        'score': score, 'mask': encode_mask(mask)})
    return objects


class MetaSam:
    """Inference callable for Monitoring, plus the status methods the app expects of its SAM worker."""
    window_frames = 1
    min_check_seconds = 1.0
    unavailable_reason = 'Camera or Meta SAM unavailable. Check the Pi connection and the internet.'
    start_message = 'SAM 3.1: Meta Model API. Camera frames are sent to Meta and each request is billed.'

    def __init__(self, log_path, config=settings, client_factory=meta_client, clock=time.monotonic):
        self.log_path = Path(log_path)
        self.config, self.client_factory, self.clock = config, client_factory, clock
        self.lock = threading.Lock()
        self.client = self.client_key = None
        self.calls = deque()

    def connection(self, values):
        """One kept-alive client: a new TLS connection for every frame would add latency."""
        key = (values.get('META_API_KEY') or values.get('MODEL_API_KEY') or '').strip()
        if not key:
            raise SegmentationError('Add META_API_KEY to the project .env to use Meta SAM.', 503)
        timeout = self.timeout_seconds(values)
        with self.lock:
            if self.client is None or self.client_key != (key, timeout):
                if self.client is not None:
                    self.client.close()
                self.client = self.client_factory(key, values.get('META_BASE_URL') or 'https://api.meta.ai/v1', timeout)
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
        values = self.config()
        client, timeout = self.connection(values)
        began = self.clock()
        status, objects = 'error', []
        image = 'data:image/jpeg;base64,'+base64.b64encode(jpeg).decode('ascii')
        try:
            response = client.responses.create(
                model=values.get('META_SAM_MODEL') or 'sam-3.1',
                input=[{'role': 'user', 'content': [{'type': 'input_text', 'text': prompt},
                                                    {'type': 'input_image', 'image_url': image}]}],
                metadata={'mask_encoding': 'one_bit', 'include_confidence': 'true'})
            # The client's timeout covers each network step; this one covers the whole answer.
            if self.clock()-began > timeout:
                status = 'late'
                raise SegmentationError('Meta SAM answered after the timeout.', 504)
            if response.status != 'completed':
                raise SegmentationError('Meta returned an incomplete segmentation.')
            objects = parse_objects(response.output_text or '', width, height)
            status = 'ok'
            return objects, width, height
        except APITimeoutError:
            status = 'timeout'
            raise SegmentationError('Meta SAM timed out.', 504) from None
        except APIConnectionError:
            status = 'connection'
            raise SegmentationError('Cannot reach Meta. Check the internet connection.', 503) from None
        except APIStatusError as error:
            status = f'http_{error.status_code}'
            raise SegmentationError(STATUS_MESSAGES.get(error.status_code, 'Meta rejected the SAM request.'),
                                    error.status_code) from None
        except SegmentationError:
            raise
        except Exception:
            raise SegmentationError('Meta SAM request failed.') from None
        finally:
            self.record(prompt, (self.clock()-began)*1000, objects, status)

    def record(self, phrase, milliseconds, objects, status):
        scores = [obj['score'] for obj in objects if obj['score'] is not None]
        with self.lock:
            now = self.clock()
            self.calls.append(now)
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
                    writer.writerow([datetime.now(timezone.utc).isoformat(timespec='milliseconds'), 'meta_api', phrase,
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
            return dict(state='failed', message='Add META_API_KEY to the project .env to use Meta SAM.',
                        owned=False, backend='meta_api')
        with self.lock:
            now = self.clock()
            calls = sum(1 for moment in self.calls if now-moment <= 3600)
        return dict(state='ready', owned=False, backend='meta_api', calls_last_hour=calls,
                    message=f'SAM 3.1 through the Meta Model API. {calls} requests in the last hour, '
                            f'about ${calls*PRICE_PER_IMAGE:.2f}.')

    def start(self):
        pass

    def restart(self):
        return self.status()

    def stop(self, wait=False):
        with self.lock:
            if self.client is not None:
                self.client.close()
            self.client = self.client_key = None
