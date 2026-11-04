"""Printer demo Gateway endpoint bridge. Runs in Ignition Jython 2.7."""
import math
import re
from java.util import UUID, Base64
from java.util.concurrent.atomic import AtomicBoolean
from java.util.concurrent.locks import ReentrantLock

ROOT = '[default]BambuP1S'
_ready = False
_tick_lock = ReentrantLock()
_busy = AtomicBoolean(False)
_pause_busy = AtomicBoolean(False)
_machine_lock = ReentrantLock()
_resume_request = None
_client = system.net.httpClient(timeout=3000)
_log = system.util.getLogger('PrinterStatus')
_latest = ''
_event_lock = ReentrantLock()
_last_status = None
_request_lock = ReentrantLock()
_request_session = str(UUID.randomUUID())
_request_sequence = 0
_request_counts = {'Start': 0, 'Stop': 0, 'Reset': 0}
_heartbeat_counter = 0


def _request_document(action='', target='farm'):
    return {'schema_version': 1, 'session_id': _request_session,
            'sequence': _request_sequence, 'request_id': str(UUID.randomUUID()) if action else '',
            'action': action, 'target': target,
            'requested_at': system.date.format(system.date.now(), "yyyy-MM-dd'T'HH:mm:ss.SSSZ") if action else '',
            'counts': dict(_request_counts)}


def _write(values):
    paths = list(values.keys())
    codes = system.tag.writeBlocking([ROOT + '/' + p for p in paths], [values[p] for p in paths], 5000)
    if any(not q.isGood() for q in codes):
        raise RuntimeError('Printer tag write failed; check provider and tag paths')


def _read(path):
    q = system.tag.readBlocking([ROOT + '/' + path], 3000)[0]
    if not q.quality.isGood():
        raise RuntimeError('Bad tag quality: ' + path)
    return q.value


def _url():
    url = str(_read('Config/ServiceUrl')).rstrip('/')
    if not re.match(r'^http://(127\.0\.0\.1|localhost):[0-9]{4,5}$', url):
        raise ValueError('Use the local connector URL')
    return url


def initialize():
    global _ready, _resume_request
    if _ready:
        return
    def missing(parent, nodes):
        for node in nodes:
            path = parent + ('' if parent.endswith(']') else '/') + node['name']
            if not system.tag.exists(path):
                codes = system.tag.configure(parent, [node], 'a')
                if any(not q.isGood() for q in codes):
                    raise RuntimeError('Could not create ' + path)
            elif node.get('tagType') == 'Folder':
                missing(path, node.get('tags', []))
    missing('[default]', TAGS)
    _resume_request = None
    _write({'System/Message': 'Reset, then System Start required',
            'System/Enabled': False, 'System/ResetValid': False, 'System/ResumeAllowed': False,
            'Controls/Request': system.util.jsonEncode(_request_document()),
            'Controls/Message': 'No request; machine action mapping belongs to SCADA',
            'Controls/HeartbeatCounter': _heartbeat_counter,
            'Vision/TagsGood': False, 'Camera/Available': False,
            'Commands/Pause': False, 'Commands/Resume': False, 'Commands/Stop': False,
            'Commands/Busy': False, 'Connection/ServiceOnline': False,
            'Connection/MqttConnected': False, 'Readings/Online': False,
            'Readings/NozzleValid': False, 'Readings/BedValid': False})
    _ready = True


def system_command(action, target='farm'):
    """Execute the customer's Gateway controls; vLock receives nothing."""
    global _request_sequence
    if action not in ('Start', 'Stop', 'Reset') or target not in ('farm', 'P1S-01'):
        raise ValueError('Unknown control request')
    initialize()
    _request_lock.lock()
    try:
        if not _read('Config/ControlRequestsEnabled'):
            raise ValueError('SCADA control requests are disabled in Config/ControlRequestsEnabled')
        message = printerSite.system_command(action)
        doc = _request_document(action, target)
        doc['sequence'] = _request_sequence + 1
        doc['counts'][action] += 1
        # One String write is a coherent document for local site scripts.
        _write({'Controls/Request': system.util.jsonEncode(doc)})
        _request_sequence = doc['sequence']
        _request_counts[action] = doc['counts'][action]
        _write({'Controls/Message': message})
        _event(action + ' for ' + target + ': ' + message)
    finally:
        _request_lock.unlock()


def _event(message):
    _event_lock.lock()
    try:
        try:
            events = list(system.util.jsonDecode(str(_read('System/Events'))))
        except Exception:
            events = []
        events.insert(0, {'time': system.date.format(system.date.now(), 'HH:mm:ss'),
                          'printer': 'P1S-01', 'event': str(message)[:300]})
        _write({'System/Events': system.util.jsonEncode(events[:25])})
    except Exception:
        _log.warn('Event feed unavailable')
    finally:
        _event_lock.unlock()


def _update_vision():
    """Read endpoint diagnostics only. Site scripts own all machine decisions."""
    values = {'Vision/TagsGood': False, 'Vision/State': 'Unavailable',
              'Vision/Quality': 'Unknown', 'Vision/Reason': 'Map Config/VisionZonePath to the imported zone',
              'Vision/BridgeOnline': False, 'Vision/HeartbeatCounter': 0}
    try:
        zone = str(_read('Config/VisionZonePath')).rstrip('/')
        if not re.match(r'^\[default\]vLock/[A-Za-z0-9_-]+$', zone):
            raise ValueError('Use a fixed vLock zone tag folder')
        paths = [zone + '/State', zone + '/Quality', zone + '/Reason',
                 '[default]vLock/Bridge/Online', '[default]vLock/Bridge/HeartbeatCounter']
        state, quality, reason, online, counter = system.tag.readBlocking(paths, 1000)
        good = all(q.quality.isGood() for q in (state, quality, reason, online, counter))
        if good:
            values.update({'Vision/TagsGood': True, 'Vision/State': str(state.value),
                           'Vision/Quality': str(quality.value), 'Vision/Reason': str(reason.value)[:250],
                           'Vision/BridgeOnline': online.value == True,
                           'Vision/HeartbeatCounter': int(counter.value)})
    except Exception:
        pass
    _write(values)


def camera_snapshot():
    """Gateway fetch of original JPEG bytes; browser receives no connector credentials."""
    try:
        response = _client.get(_url() + '/camera.jpg', timeout=750)
        if not response.good:
            raise ValueError('No fresh camera frame')
        body = response.body
        if not 4 <= len(body) <= 1024 * 1024:
            raise ValueError('Camera frame unavailable or too large')
        return {'source': 'data:image/jpeg;base64,' + Base64.getEncoder().encodeToString(body),
                'message': 'Printer camera | refresh every 1 second'}
    except Exception:
        return {'source': '', 'message': 'Camera unavailable; check connector camera setting and printer connection'}


def command(action):
    global _resume_request
    if action not in ('Pause', 'Resume', 'Stop'):
        raise ValueError('Unknown printer action')
    initialize()
    if action == 'Resume':
        _resume_request = printerSite.resume_token()
    _write({'Commands/' + action: True})


def _dispatch(action):
    global _latest, _resume_request
    token = _resume_request if action == 'Resume' else None
    if action == 'Resume':
        _resume_request = None
        if token is None:
            _write({'Commands/Result': 'Resume refused; use the operator Resume button'})
            return
    gate = _pause_busy if action == 'Pause' else _busy
    if action != 'Stop' and not gate.compareAndSet(False, True):
        _write({'Commands/Result': 'Command busy; request was not sent'})
        return
    request_id = str(UUID.randomUUID())
    _latest = request_id
    def result(text):
        if _latest == request_id:
            _write({'Commands/Result': text})
    if action != 'Stop':
        _write({'Commands/Busy': True})
    result(action + ' requested; waiting for printer response')
    _event(action + ' requested')
    def worker():
        locked = False
        try:
            if action != 'Stop':
                # A queued Pause waits for any already-sent Resume to finish.
                # The site watchdog never waits on this HTTP/command lock.
                _machine_lock.lock()
                locked = True
            response = _client.get(_url() + '/status', timeout=3000)
            if not response.good:
                raise RuntimeError('Connector unavailable')
            status = response.json
            if not status.get('online') or not status.get('mqtt_connected'):
                raise RuntimeError('Printer disconnected or telemetry stale')
            if action == 'Resume' and status.get('state') != 'Paused':
                raise RuntimeError('Resume requires a paused print')
            if action == 'Pause' and status.get('state') != 'Running':
                raise RuntimeError('Pause requires a running print')
            if action == 'Resume':
                printerSite.check_resume(token)
            # Resume is distinct from Start. Older connectors reject it safely.
            response = _client.post(_url() + '/command',
                data={'action': action, 'id': request_id}, timeout=16000)
            body = response.json
            message = str(body.get('result') if response.good else body.get('error', 'Command rejected'))
            result(message)
            _event(message)
        except Exception as exc:
            result('Not confirmed: ' + str(exc) + '. Check actual printer state before retrying.')
            _event(action + ' not confirmed; check printer state before retrying')
        finally:
            if locked:
                _machine_lock.unlock()
            if action != 'Stop':
                gate.set(False)
                _write({'Commands/Busy': _busy.get() or _pause_busy.get()})
    system.util.invokeAsynchronous(worker)


def tick():
    global _last_status, _heartbeat_counter
    if not _tick_lock.tryLock():
        return
    try:
        initialize()
        values = {'Connection/LastPoll': system.date.now(),
                  'Connection/ServiceOnline': False, 'Connection/MqttConnected': False,
                  'Connection/Message': 'Connector unavailable',
                  'Readings/Online': False, 'Readings/State': 'Offline',
                  'Readings/NozzleValid': False, 'Readings/BedValid': False,
                  'Readings/ProgressValid': False, 'Readings/RemainingValid': False,
                  'Readings/FileName': '', 'Camera/Available': False}
        try:
            response = _client.get(_url() + '/status', timeout=3000)
            if not response.good:
                raise RuntimeError('Status HTTP ' + str(response.statusCode))
            s = response.json
            online = bool(s.get('online') and s.get('mqtt_connected'))
            values.update({'Connection/ServiceOnline': True,
                           'Connection/MqttConnected': bool(s.get('mqtt_connected')),
                           'Connection/Message': 'Receiving printer reports' if online else 'Printer disconnected or reports stale',
                           'Readings/Online': online,
                           'Readings/State': str(s.get('state', 'Unknown')) if online else 'Offline',
                           'Readings/RawState': str(s.get('raw_state', '')) if online else '',
                           'Readings/FileName': str(s.get('file_name', ''))[:250] if online else '',
                           'Readings/Fault': bool(s.get('fault')) if online else False,
                           'Readings/FaultMessage': str(s.get('fault_message', ''))[:250] if online else '',
                           'Camera/Available': bool(s.get('camera_available'))})
            if s.get('age_seconds') is not None:
                values['Readings/AgeSeconds'] = float(s['age_seconds'])
            for field, tag, valid in [('nozzle_temp', 'NozzleTemp', 'NozzleValid'),
                                      ('bed_temp', 'BedTemp', 'BedValid'),
                                      ('progress', 'Progress', 'ProgressValid'),
                                      ('remaining_seconds', 'RemainingSeconds', 'RemainingValid')]:
                v = s.get(field)
                good = online and isinstance(v, (int, long, float)) and not isinstance(v, bool) and not math.isnan(v) and not math.isinf(v)
                if field == 'progress':
                    good = good and 0 <= v <= 100
                if field == 'remaining_seconds':
                    good = good and 0 <= v <= 2147483647
                values['Readings/' + valid] = good
                if good:
                    values['Readings/' + tag] = int(v) if field == 'remaining_seconds' else float(v)
        except Exception:
            _log.warn('Printer status unavailable; readings marked invalid')
        _write(values)
        current = (values['Readings/Online'], values['Readings/State'])
        if current != _last_status:
            _event('Printer ' + current[1])
            _last_status = current
        _update_vision()
        _heartbeat_counter += 1
        _write({'Controls/HeartbeatCounter': _heartbeat_counter})
        # Only the operator path may supply a Resume token; site logic requests Pause only.
        # Consume momentary request tags once, with Stop taking precedence.
        actions = [a for a in ('Stop', 'Pause', 'Resume') if _read('Commands/' + a)]
        if actions:
            _write({'Commands/' + a: False for a in actions})
            _dispatch(actions[0])
    except Exception as exc:
        _log.error(str(exc))
    finally:
        _tick_lock.unlock()


TAGS = [{'name': 'BambuP1S', 'tagType': 'Folder', 'tags': [{'name': 'Config', 'tagType': 'Folder', 'tags': [{'name': 'ServiceUrl', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'http://127.0.0.1:8876'}, {'name': 'VisionZonePath', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': '[default]vLock/A-101'}, {'name': 'ControlRequestsEnabled', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': True}]}, {'name': 'Connection', 'tagType': 'Folder', 'tags': [{'name': 'ServiceOnline', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'Message', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'Waiting for local connector'}, {'name': 'LastPoll', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'DateTime'}, {'name': 'MqttConnected', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}]}, {'name': 'Readings', 'tagType': 'Folder', 'tags': [{'name': 'Online', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'State', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'Offline'}, {'name': 'RawState', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': ''}, {'name': 'FileName', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': ''}, {'name': 'NozzleTemp', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Float8', 'value': 0}, {'name': 'BedTemp', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Float8', 'value': 0}, {'name': 'Progress', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Float8', 'value': 0}, {'name': 'RemainingSeconds', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Int4', 'value': 0}, {'name': 'FilamentRemaining', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Float8', 'value': 0}, {'name': 'AgeSeconds', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Float8', 'value': 0}, {'name': 'Fault', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False, 'alarms': [{'name': 'PrinterFault', 'mode': 'Equality', 'setpointA': 1, 'priority': 'High', 'ackMode': 'Unused', 'label': 'Bambu P1S machine fault'}]}, {'name': 'FaultMessage', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': ''}, {'name': 'NozzleValid', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'BedValid', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'ProgressValid', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'RemainingValid', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'FilamentValid', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}]}, {'name': 'Commands', 'tagType': 'Folder', 'tags': [{'name': 'Result', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'No command requested'}, {'name': 'Pause', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'Resume', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'Stop', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'Busy', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}]}, {'name': 'System', 'tagType': 'Folder', 'tags': [{'name': 'Message', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'Reset, then System Start required'}, {'name': 'Events', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': '[]'}, {'name': 'Enabled', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'StopLatched', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False, 'valuePersistence': 'Database'}, {'name': 'ResetValid', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'CanReset', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'ResumeAllowed', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'HeartbeatMoving', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'StopReason', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': ''}]}, {'name': 'Vision', 'tagType': 'Folder', 'tags': [{'name': 'TagsGood', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'State', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'Unavailable'}, {'name': 'Quality', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'Unknown'}, {'name': 'Reason', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'Map the imported zone'}, {'name': 'BridgeOnline', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'HeartbeatCounter', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Int8', 'value': 0}]}, {'name': 'Controls', 'tagType': 'Folder', 'tags': [{'name': 'Request', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': '{"schema_version": 1, "session_id": "", "sequence": 0, "request_id": "", "action": "", "target": "farm", "requested_at": "", "counts": {"Start": 0, "Stop": 0, "Reset": 0}}'}, {'name': 'Message', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'No request; machine action mapping belongs to SCADA'}, {'name': 'HeartbeatCounter', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Int8', 'value': 0}]}, {'name': 'Camera', 'tagType': 'Folder', 'tags': [{'name': 'Available', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'Source', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': ''}, {'name': 'Message', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'No fresh camera frame'}]}]}]
