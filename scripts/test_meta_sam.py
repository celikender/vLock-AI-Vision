"""Connectivity and latency test for SAM 3.1 and Muse Spark on the Meta Model API.

Sends one local frame to Meta. Run from the project folder:
    .venv\\Scripts\\python.exe scripts/test_meta_sam.py [image.jpg]
The key comes from .env or the environment (META_API_KEY or MODEL_API_KEY) and is never printed.
"""
import base64
import os
import re
import sys
import time
from pathlib import Path

from dotenv import dotenv_values
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

ROOT = Path(__file__).resolve().parents[1]
PHRASES = ['dog', 'person']
CONTROL_PHRASE = 'storage drawers'  # Expected to match the sample frame, so box parsing is exercised.
RUNS = 10
TIMEOUT_SECONDS = 60
RAW_PREVIEW = 400
MUSE_PROMPT = 'Is there a person or animal in this image? Answer JSON.'
BOX = re.compile(r'<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)(?:;c=([0-9.]+))?\|>')
ACCESS_ERRORS = {401, 402, 403, 404}


class AccessError(Exception):
    """The key or account cannot use this model; further calls would fail the same way."""


def parse_boxes(text):
    return [{'box': [int(value) for value in match[:4]], 'frame': [int(match[4]), int(match[5])],
             'score': float(match[6]) if match[6] else None} for match in BOX.findall(text)]


def preview(text):
    return text if len(text) <= RAW_PREVIEW else f'{text[:RAW_PREVIEW]}... ({len(text)} characters)'


def call(client, model, content, metadata=None):
    """One request with no retries. Returns (status, milliseconds, output text)."""
    began = time.perf_counter()
    options = {'metadata': metadata} if metadata else {}
    raw = client.responses.with_raw_response.create(
        model=model, input=[{'role': 'user', 'content': content}], **options)
    response = raw.parse()
    elapsed = (time.perf_counter() - began) * 1000
    if response.status != 'completed':
        raise RuntimeError(f'response status {response.status}')
    return raw.status_code, elapsed, response.output_text or ''


def sam_content(phrase, image):
    return [{'type': 'input_text', 'text': phrase}, image]


def upload(client, path):
    with path.open('rb') as handle:
        return client.files.create(file=handle, purpose='user_data').id


def run(label, runs, request, show=None):
    """Repeat one call, print every outcome, and return the latencies of the successes."""
    print(f'\n=== {label} ({runs} run(s)) ===')
    times, failures = [], 0
    for number in range(1, runs + 1):
        try:
            status, elapsed, text = request()
        except APIStatusError as error:
            code = getattr(error, 'code', None)
            print(f'  run {number}: HTTP {error.status_code} code={code}')
            if error.status_code in ACCESS_ERRORS:
                raise AccessError(f'{label}: HTTP {error.status_code} code={code}') from None
            failures += 1
            continue
        except (APITimeoutError, APIConnectionError) as error:
            print(f'  run {number}: {type(error).__name__}')
            failures += 1
            continue
        except RuntimeError as error:
            print(f'  run {number}: {error}')
            failures += 1
            continue
        times.append(elapsed)
        print(f'  run {number}: HTTP {status} {elapsed:.0f} ms' + (f' {show(text)}' if show else ''))
        if number == 1:
            print(f'  raw output: {preview(text)!r}')
    if times:
        print(f'  latency ms: min {min(times):.0f} avg {sum(times) / len(times):.0f} max {max(times):.0f}'
              f' ({len(times)} ok, {failures} failed)')
    else:
        print(f'  no successful calls ({failures} failed)')
    return times


def show_boxes(text):
    boxes = parse_boxes(text)
    return f'{len(boxes)} match(es) {boxes}' if boxes else '0 matches'


def base64_rejected(client, model, image):
    """Try the frame inline once. Returns True only when Meta refuses the request as invalid."""
    try:
        status, elapsed, _ = call(client, model, sam_content(CONTROL_PHRASE, image))
    except APIStatusError as error:
        print(f'Inline base64 check: HTTP {error.status_code} code={getattr(error, "code", None)}')
        if error.status_code in ACCESS_ERRORS:
            raise AccessError(f'SAM access: HTTP {error.status_code}') from None
        return error.status_code == 400
    print(f'Inline base64 check: accepted, HTTP {status}, {elapsed:.0f} ms')
    return False


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'samples' / 'frame.jpg'
    if not path.is_file():
        sys.exit(f'Test frame not found: {path}')
    config = {**dotenv_values(ROOT / '.env'), **os.environ}
    key = (config.get('MODEL_API_KEY') or config.get('META_API_KEY') or '').strip()
    if not key:
        sys.exit('No key: set MODEL_API_KEY or META_API_KEY in .env.')
    base_url = config.get('META_BASE_URL') or 'https://api.meta.ai/v1'
    sam_model = config.get('META_SAM_MODEL') or 'sam-3.1'
    muse_model = config.get('META_MUSE_MODEL') or 'muse-spark-1.3'
    jpeg = path.read_bytes()
    print(f'Frame: {path.name}, {len(jpeg)} bytes. Base URL: {base_url}. SAM: {sam_model}. Muse: {muse_model}.')
    image = {'type': 'input_image', 'image_url': 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode('ascii')}
    metadata = {'mask_encoding': 'one_bit', 'include_confidence': 'true'}
    with OpenAI(api_key=key, base_url=base_url, timeout=TIMEOUT_SECONDS, max_retries=0) as client:
        try:
            if base64_rejected(client, sam_model, image):
                print('Inline base64 refused: retrying through the Files API.')
                image = {'type': 'input_image', 'file_id': upload(client, path)}
            for phrase in PHRASES:
                run(f'SAM "{phrase}"', RUNS, lambda p=phrase: call(client, sam_model, sam_content(p, image), metadata),
                    show_boxes)
            run(f'SAM control "{CONTROL_PHRASE}"', 1,
                lambda: call(client, sam_model, sam_content(CONTROL_PHRASE, image), metadata), show_boxes)
            run('Muse Spark', RUNS,
                lambda: call(client, muse_model, [{'type': 'input_text', 'text': MUSE_PROMPT}, image]),
                lambda text: preview(' '.join(text.split())))
        except AccessError as error:
            sys.exit(f'\nSTOP: this key cannot use the model. {error}')


if __name__ == '__main__':
    main()
