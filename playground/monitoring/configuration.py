"""Validated local monitoring configuration. Credentials never enter public views."""
import copy
import ipaddress
import json
import math
import os
from pathlib import Path
from urllib.parse import urlsplit


DEFAULT = {
    'version': 1,
    'camera': {'id': 'CAM_01', 'name': 'Conveyor Camera 01', 'url': 'http://192.168.1.254:8080',
               'username': '', 'password': '', 'frame_size': None},
    'sam_prompt': 'person',
    'zone': {'name': 'Conveyor Zone A', 'polygon': [], 'frame_size': None},
    'rule': {'condition': 'mask_overlaps_zone', 'min_overlap_ratio': 0.1,
             'persistence_seconds': 0.5, 'action': 'warning'},
}


def text(value, label, limit=200):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        raise ValueError(f'Enter {label} (1–{limit} characters).')
    return value.strip()


def camera_url(value):
    value = text(value, 'a camera IP address or HTTP URL', 300)
    parsed = urlsplit(value if '://' in value else 'http://' + value)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('Enter camera credentials in the separate credential fields.')
    if parsed.scheme != 'http' or parsed.path not in ('', '/', '/snapshot.jpg', '/stream.mjpg') or parsed.query or parsed.fragment:
        raise ValueError('Use the Pi HTTP address. RTSP and other camera protocols are not supported yet.')
    try:
        address = ipaddress.IPv4Address(parsed.hostname)
        port = 8080 if parsed.port is None else parsed.port
        if not 1<=port<=65535 or not any(address in ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Use a private LAN IPv4 address and valid port.') from None
    return f'http://{address}:{port}'


def number(value, low, high, label):
    if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label} must be between {low} and {high}.')
    return float(value)


def frame_size(value):
    if value is None:
        return None
    if (not isinstance(value, list) or len(value) != 2 or
            any(type(n) is not int or not 1 <= n <= 4096 for n in value) or value[0] * value[1] > 2_000_000):
        raise ValueError('Use a camera frame of at most 2 megapixels.')
    return list(value)


def cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def intersects(a, b, c, d):
    def on(p, q, r):
        return abs(cross(p, q, r)) < 1e-8 and min(p[0],q[0]) <= r[0] <= max(p[0],q[0]) and min(p[1],q[1]) <= r[1] <= max(p[1],q[1])
    return ((cross(a,b,c)*cross(a,b,d) < 0 and cross(c,d,a)*cross(c,d,b) < 0) or
            on(a,b,c) or on(a,b,d) or on(c,d,a) or on(c,d,b))


def polygon(points, size):
    if not isinstance(points, list) or len(points) > 32:
        raise ValueError('Use a polygon with 3–32 vertices.')
    if not points:
        return []
    if len(points) < 3 or size is None:
        raise ValueError('Connect the camera and draw at least three zone points.')
    result = []
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError('Invalid zone vertex.')
        result.append([number(point[0], 0, size[0]-1, 'Zone X'), number(point[1], 0, size[1]-1, 'Zone Y')])
    if len({tuple(p) for p in result}) != len(result):
        raise ValueError('Zone vertices must be distinct.')
    area = abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(result, result[1:]+result[:1]))) / 2
    if area < 4:
        raise ValueError('Draw a zone with a visible area.')
    for i in range(len(result)):
        for j in range(i+1, len(result)):
            if j == i+1 or (i == 0 and j == len(result)-1):
                continue
            if intersects(result[i], result[(i+1)%len(result)], result[j], result[(j+1)%len(result)]):
                raise ValueError('Zone edges must not cross or touch each other.')
    return result


def validate(data, previous=None, require_zone=False):
    if not isinstance(data, dict):
        raise ValueError('Expected a monitoring configuration.')
    old = previous or DEFAULT
    result = copy.deepcopy(DEFAULT)
    camera = data.get('camera', {})
    zone = data.get('zone', {})
    rule = data.get('rule', {})
    if not all(isinstance(part, dict) for part in (camera, zone, rule)):
        raise ValueError('Invalid configuration sections.')
    result['camera']['name'] = text(camera.get('name', old['camera']['name']), 'a camera name', 80)
    result['camera']['url'] = camera_url(camera.get('url', old['camera']['url']))
    same_camera = result['camera']['url'] == old['camera']['url']
    for key in ('username', 'password'):
        supplied = camera.get(key)
        if supplied is not None and (not isinstance(supplied, str) or len(supplied) > 256 or '\r' in supplied or '\n' in supplied):
            raise ValueError('Invalid camera credentials.')
        result['camera'][key] = (supplied if supplied else old['camera'].get(key, '') if same_camera else '')
        if camera.get('clear_credentials'):
            result['camera'][key] = ''
    result['camera']['frame_size'] = frame_size(old['camera']['frame_size'] if same_camera else None)
    result['sam_prompt'] = text(data.get('sam_prompt', old['sam_prompt']), 'a detection target')
    result['zone']['name'] = text(zone.get('name', old['zone']['name']), 'a zone name', 80)
    result['zone']['frame_size'] = frame_size(zone.get('frame_size', old['zone']['frame_size']))
    result['zone']['polygon'] = polygon(zone.get('polygon', old['zone']['polygon']), result['zone']['frame_size'])
    result['rule']['condition'] = rule.get('condition', old['rule']['condition'])
    if result['rule']['condition'] not in ('mask_overlaps_zone', 'mask_inside_zone', 'object_absent'):
        raise ValueError('Select a supported zone condition.')
    result['rule']['action'] = rule.get('action', old['rule']['action'])
    if result['rule']['action'] not in ('warning', 'event_log'):
        raise ValueError('SCADA output is not configured. Select warning or event log.')
    result['rule']['min_overlap_ratio'] = number(rule.get('min_overlap_ratio', old['rule']['min_overlap_ratio']), 0.001, 1, 'Overlap ratio')
    result['rule']['persistence_seconds'] = number(rule.get('persistence_seconds', old['rule']['persistence_seconds']), 0, 60, 'Persistence duration')
    if require_zone and (not result['zone']['polygon'] or result['zone']['frame_size'] != result['camera']['frame_size']):
        raise ValueError('Connect the camera, then save a polygon matching its current resolution.')
    return result


def public(config):
    view = copy.deepcopy(config)
    camera = view['camera']
    camera['credentials_configured'] = bool(camera.pop('username') or camera.get('password'))
    camera.pop('password')
    return view


class Store:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return copy.deepcopy(DEFAULT)
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            result = validate(data, data)
            result['camera']['frame_size'] = frame_size(data['camera'].get('frame_size'))
            return result
        except (ValueError, KeyError, TypeError):
            raise ValueError('Saved monitoring configuration is invalid; it was not overwritten.') from None

    def save(self, config):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        with open(temporary, 'w', encoding='utf-8') as file:
            json.dump(config, file, indent=2, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(self.path)
