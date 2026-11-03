"""Fixed SCADA tags per zone: every zone publishes the same names, so bindings survive rule and output changes."""
import re
from datetime import datetime

KEY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,39}')
NAMESPACE_URI = 'urn:vlock:bridge:v1'
UDT_NAME = 'vLockZone'
DEFAULT_OPC_SERVER = 'vLock Bridge'

# (tag, OPC UA type, Ignition type, meaning). The order is the display and UDT order.
TAGS = [
    ('Active', 'Boolean', 'Boolean', 'True when the zone rule is met. Bad quality when Unknown or for count zones.'),
    ('State', 'String', 'String', 'Active, Clear, Valid (count zones) or Unknown.'),
    ('Quality', 'String', 'String', 'Good, Unknown or Stale.'),
    ('Reason', 'String', 'String', 'Why the zone has this state.'),
    ('Count1', 'Int32', 'Int4', 'Detections of Object1 in the whole frame. Bad quality when Unknown.'),
    ('Count2', 'Int32', 'Int4', 'Detections of Object2 in the whole frame. Bad quality when Unknown or unused.'),
    ('Score1', 'Double', 'Float8', 'Highest SAM score for Object1, 0-1. Diagnostic only, not a calibrated probability.'),
    ('Score2', 'Double', 'Float8', 'Highest SAM score for Object2, 0-1. Diagnostic only, not a calibrated probability.'),
    ('ObservedAt', 'String', 'String', 'UTC time of the analysed camera frame.'),
    ('AgeSeconds', 'Double', 'Float8', 'Seconds between ObservedAt and this update.'),
    ('CheckSeconds', 'Double', 'Float8', 'SAM time of the last check.'),
    ('ZoneName', 'String', 'String', 'Zone name shown in the app.'),
    ('ZoneId', 'String', 'String', 'Internal zone id.'),
    ('OutputName', 'String', 'String', 'Output name from the rule. Changing it never moves these tags.'),
    ('OutputType', 'String', 'String', 'condition, event or count.'),
    ('Rule', 'String', 'String', 'The rule in plain words.'),
    ('Object1', 'String', 'String', 'First object SAM looks for.'),
    ('Object2', 'String', 'String', 'Second object; empty for one-object zones.'),
    ('Skill', 'String', 'String', 'Skill (scenario package) this zone follows, or empty.'),
    ('VlmState', 'String', 'String', 'Answer of the optional Muse frame check (for example yes, no, unsure), '
     'or off, pending or error. Advisory: never changes Active or State.'),
    ('VlmReason', 'String', 'String', 'Muse frame-check reason, or why no check ran.'),
    ('VlmCheckedAt', 'String', 'String', 'UTC time of the last Muse frame check.'),
]
VLM_OFF = dict(VlmState='off', VlmReason='', VlmCheckedAt='')
BRIDGE_TAGS = [('Online', 'Boolean', 'Boolean'), ('Status', 'String', 'String'),
               ('Heartbeat', 'String', 'String'), ('HeartbeatCounter', 'Int64', 'Int8')]

RELATIONS = {'overlaps area': 'overlaps the area', 'entirely inside area': 'is entirely inside the area',
             'absent from area': 'is absent from the area'}
REASONS = {'stale': 'No fresh result: monitoring is off or checks are late.',
           'restart': 'Application restarted; waiting for a fresh check.'}


def tag_key(name, taken):
    """A readable, unique key from the zone name, fixed once the zone first gets tags."""
    base = re.sub(r'[^A-Za-z0-9_-]+', '-', name).strip('-_')[:36] or 'zone'
    if not base[0].isalnum():
        base = 'z' + base
    key, number = base, 2
    while key.lower() in {k.lower() for k in taken}:
        key, number = f'{base}-{number}', number + 1
    return key


def rule_text(zone):
    def part(target, relation):
        return f'{target} {RELATIONS.get(relation, relation)}'
    text = part(zone['target'], zone['firstRelation'])
    if zone['extraConditions']:
        extra = zone['extraConditions'][0]
        join = 'AND' if zone['ruleJoin'] == 'ALL (AND)' else 'OR'
        text += f' {join} ' + part(extra['object'], extra['relation'])
    return f'{text} for {zone["persistence"]:g} s'


def manifest(zone):
    """The descriptive half of a zone's tags; values come from observations."""
    extra = zone['extraConditions'][:1]
    return dict(TagKey=zone['tagKey'], ZoneName=zone['name'], ZoneId=zone['id'], OutputName=zone['output'],
                OutputType=zone['outputType'], Rule=rule_text(zone), Object1=zone['target'],
                Object2=extra[0]['object'] if extra else '', Skill=zone.get('skill', ''))


def seconds(stamp):
    return datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()


def document(zone, signal, now):
    doc = dict(zone, Active=None, State='Unknown', Quality='Unknown', Count1=None, Count2=None, Score1=None,
               Score2=None, ObservedAt=None, AgeSeconds=None, CheckSeconds=None,
               Reason='No observation yet. Save the rule and enable monitoring.')
    if signal is None:
        return doc
    status = signal['status']
    doc['ObservedAt'] = signal['observed_at']
    doc['AgeSeconds'] = round(max(0., now - seconds(signal['observed_at'])), 2)
    if status not in ('active', 'clear', 'valid'):
        doc['Quality'] = 'Stale' if status == 'stale' else 'Unknown'
        doc['Reason'] = REASONS.get(signal.get('unavailable_reason')) or signal.get('reason') or doc['Reason']
        return doc
    details = signal.get('details') or {}
    if signal['kind'] == 'condition':
        doc['Active'] = status == 'active'
    elif zone['OutputType'] == 'event':
        doc['Active'] = (signal.get('value') or {}).get('state') == 'Warning'
    doc['State'] = 'Valid' if doc['Active'] is None else 'Active' if doc['Active'] else 'Clear'
    doc['Quality'] = 'Good'
    doc['Reason'] = signal.get('reason') or doc['State']
    counts, scores = details.get('counts') or {}, details.get('scores') or {}
    for index, name in enumerate((zone['Object1'], zone['Object2']), 1):
        if name:
            doc[f'Count{index}'] = counts.get(name)
            doc[f'Score{index}'] = scores.get(name)
    if isinstance(details.get('check_seconds'), (int, float)):
        doc['CheckSeconds'] = details['check_seconds']
    return doc


def documents(snapshot, zones, now, checks=None):
    assets = {asset['asset_id']: asset for asset in snapshot['assets']}
    result = []
    for zone in zones:
        signals = assets.get(zone['ZoneId'], {}).get('signals', [])
        signal = next((s for s in signals if s['source_id'] == 'vision' and s['signal_id'] == zone['OutputName']), None)
        # The frame check sits beside the SAM result and never alters it.
        result.append(dict(Skill='') | document(zone, signal, now) | VLM_OFF | ((checks or {}).get(zone['ZoneId']) or {}))
    return result


def removed(key):
    """Values kept for a key whose zone left the workspace, until the next restart."""
    empty = dict(TagKey=key, ZoneName='', ZoneId='', OutputName='', OutputType='', Rule='', Object1='', Object2='', Skill='')
    return document(empty, None, 0) | VLM_OFF | dict(Reason='Zone removed from the workspace.')


def node_id(key, tag):
    return f'Bridge/Zones/{key}/{tag}'


def ignition_export(zones, opc_server=DEFAULT_OPC_SERVER):
    """Ignition tag import: one vLockZone UDT plus an instance per zone and the bridge heartbeat tags."""
    def opc(path, data_type, parameter=True):
        return dict(tagType='AtomicTag', valueSource='opc', dataType=data_type,
                    opcServer=dict(bindType='parameter', binding='{OpcServer}') if parameter else opc_server,
                    opcItemPath=dict(bindType='parameter', binding=f'nsu={NAMESPACE_URI};s={path}') if parameter
                    else f'nsu={NAMESPACE_URI};s={path}')
    udt = dict(name=UDT_NAME, tagType='UdtType',
               parameters=dict(ZoneKey=dict(dataType='String', value=''),
                               OpcServer=dict(dataType='String', value=opc_server)),
               tags=[dict(opc(node_id('{ZoneKey}', tag), ignition), name=tag, documentation=meaning)
                     for tag, _, ignition, meaning in TAGS])
    instances = [dict(name=zone['TagKey'], tagType='UdtInstance', typeId=UDT_NAME,
                      parameters=dict(ZoneKey=dict(dataType='String', value=zone['TagKey'])))
                 for zone in zones]
    bridge = dict(name='Bridge', tagType='Folder',
                  tags=[dict(opc('Bridge/' + tag, ignition, parameter=False), name=tag) for tag, _, ignition in BRIDGE_TAGS])
    return dict(tags=[dict(name='_types_', tagType='Folder', tags=[udt]),
                      dict(name='vLock', tagType='Folder', tags=[bridge] + instances)])
