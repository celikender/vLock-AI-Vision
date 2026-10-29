"""Experimental Claude posture observations and seated-to-standing transitions."""
import base64
import json
import sys
import time
from io import BytesIO
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'camera'))
from analysis import analyze_photo
from masks import prepare

SCHEMA = {'type':'object','properties': {
    'posture':{'type':'string','enum':['seated','standing','unknown']},
    'single_person':{'type':'boolean'}, 'explanation':{'type':'string'}},
    'required':['posture','single_person','explanation'],'additionalProperties':False}


def observe_posture(jpeg):
    image = prepare(jpeg, 'person')
    buffer = BytesIO()
    image.save(buffer, 'JPEG', quality=85)
    data = buffer.getvalue()
    result = analyze_photo(data,
        'Classify the physical posture of the sole person in this image as seated or standing. '
        'Use unknown if no person, multiple people, an obscured lower body, a partial view, '
        'crouching, or insufficient visual evidence prevents a confident distinction. '
        'single_person means exactly one visible person. Do not infer motion from this image. '
        'Do not identify the person. Briefly explain visible evidence. Return the JSON schema.',
        output_schema=SCHEMA)
    output = json.loads(result['answer'])
    if output.get('posture') not in ('seated','standing','unknown') or type(output.get('single_person')) is not bool:
        raise ValueError('Invalid posture response.')
    if not isinstance(output.get('explanation'), str) or len(output['explanation']) > 1500:
        raise ValueError('Invalid posture explanation.')
    if not output['single_person']:
        output['posture'] = 'unknown'
    return {'backend':'claude','model':result['model'], 'posture':output['posture'],
            'explanation':output['explanation'], 'elapsed_seconds':result['elapsed_seconds'],
            'annotated_image':'data:image/jpeg;base64,' + base64.b64encode(data).decode('ascii')}


class StandUp:
    """Arm on two seated observations; fire on two standing observations."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.stale_seconds = 30
        self.state = 'unknown'
        self.reason = 'Waiting to confirm a seated person.'
        self.observed_at = None
        self.candidate = None
        self.hits = 0
        self.armed = False
        self.event_type = 'unknown'

    def unavailable(self, reason):
        changed = self.state != 'unknown'
        self.state, self.reason = 'unknown', reason
        self.candidate, self.hits, self.armed = None, 0, False
        self.event_type = 'unknown'
        return changed

    def expire(self):
        if self.observed_at is not None and self.clock() - self.observed_at > self.stale_seconds:
            return self.unavailable('Posture observation is stale; seated baseline must be re-established.')
        return False

    def observe(self, posture, captured_at):
        if posture not in ('seated','standing') or self.clock() - captured_at > self.stale_seconds:
            return self.unavailable('Posture uncertain or stale; waiting for a clear single-person view.')
        self.observed_at = captured_at
        self.hits = min(2, self.hits + 1) if posture == self.candidate else 1
        self.candidate = posture
        self.reason = f'{self.hits}/2 observations confirming {posture}.'
        if self.hits < 2:
            return False
        changed = self.state != posture
        self.state = posture
        self.event_type = posture + '_observed'
        if posture == 'seated':
            self.armed = True
            self.reason = 'Seated baseline confirmed. Waiting for the person to stand.'
        elif self.armed:
            self.armed = False
            self.event_type = 'person_stood_up'
            self.reason = 'Confirmed seated → standing transition.'
        else:
            self.reason = 'Standing observed. Sit down first to establish a new baseline.'
        return changed
