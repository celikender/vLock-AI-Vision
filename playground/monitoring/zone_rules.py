"""Deterministic mask geometry and warning persistence; independent of model inference."""
import time
from PIL import Image, ImageDraw, ImageChops
from video_tracking import decode_mask


def evaluate(result, config):
    size = config['zone']['frame_size']
    if [result.get('width'), result.get('height')] != size:
        raise ValueError('Camera resolution changed. Reconnect and redraw the zone.')
    objects = result.get('objects')
    if not isinstance(objects, list) or result.get('count') != len(objects) or len(objects) > 8:
        raise ValueError('Incomplete SAM mask results.')
    zone = Image.new('L', tuple(size))
    ImageDraw.Draw(zone).polygon([tuple(p) for p in config['zone']['polygon']], fill=255)
    detections = []
    for obj in objects:
        mask = decode_mask(obj['mask'])
        if mask.size != zone.size:
            raise ValueError('Mask dimensions do not match the zone.')
        area = mask.histogram()[255]
        if area == 0:
            raise ValueError('SAM returned an empty object mask.')
        overlap = ImageChops.multiply(mask, zone).histogram()[255]
        detections.append({'object_id': obj.get('object_id'), 'overlap_ratio': overlap/area,
                           'mask_pixels': area, 'zone_overlap_pixels': overlap})
    threshold = 1.0 if config['rule']['condition'] == 'mask_inside_zone' else config['rule']['min_overlap_ratio']
    matched = any(d['overlap_ratio'] >= threshold for d in detections)
    if config['rule']['condition'] == 'object_absent':
        matched = not matched
    return matched, detections


class RuleState:
    def __init__(self, duration, clock=time.monotonic, stale_seconds=10):
        self.clock, self.duration, self.stale_seconds = clock, duration, stale_seconds
        self.state, self.reason = 'Unknown', 'Waiting for fresh SAM results.'
        self.observed_at = self.candidate_at = self.candidate = None
        self.hits = 0

    def unavailable(self, reason):
        changed = self.state != 'Unknown'
        self.state, self.reason = 'Unknown', reason
        self.observed_at = self.candidate_at = self.candidate = None
        self.hits = 0
        return changed

    def expire(self):
        if self.observed_at is not None and self.clock()-self.observed_at > self.stale_seconds:
            return self.unavailable('Inference is stale. Waiting for a fresh observation.')
        return False

    def observe(self, matched, captured_at):
        previous_state = self.state
        if captured_at > self.clock():
            return self.unavailable('Camera observation timestamp is invalid.')
        if self.clock()-captured_at > self.stale_seconds:
            return self.unavailable('SAM finished on an old frame. Waiting for fresh inference.')
        if self.observed_at is not None:
            if captured_at <= self.observed_at:
                return self.unavailable('Camera observation was repeated or out of order.')
            if captured_at-self.observed_at > self.stale_seconds:
                self.unavailable('Observation gap exceeded the freshness limit.')
        self.observed_at = captured_at
        if matched != self.candidate:
            self.candidate, self.candidate_at, self.hits = matched, captured_at, 1
        else:
            self.hits += 1
        elapsed = captured_at-self.candidate_at
        if self.hits >= 2 and elapsed >= self.duration:
            state = 'Warning' if matched else 'Normal'
            changed = state != previous_state
            self.state = state
            self.reason = 'Zone condition is confirmed.' if matched else 'Zone condition is inactive.'
            return changed
        self.reason = f'Confirming {"active" if matched else "inactive"} condition: {elapsed:.1f}/{self.duration:g}s; {self.hits} observations.'
        return self.state != previous_state
