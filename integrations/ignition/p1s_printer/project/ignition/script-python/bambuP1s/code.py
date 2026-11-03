"""One-printer Gateway bridge. Runs in Ignition Jython 2.7."""
import math
import re
from java.util import UUID
from java.util.concurrent.atomic import AtomicBoolean
from java.util.concurrent.locks import ReentrantLock

ROOT = '[default]BambuP1S'
_ready = False
_tick_lock = ReentrantLock()
_busy = AtomicBoolean(False)
_client = system.net.httpClient(timeout=3000)
_log = system.util.getLogger('PrinterStatus')
_latest = ''


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
    global _ready
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
    _write({'System/Enabled': False, 'System/Message': 'Stopped; vLock pending',
            'Commands/Pause': False, 'Commands/Resume': False, 'Commands/Stop': False,
            'Commands/Busy': False, 'Connection/ServiceOnline': False,
            'Connection/MqttConnected': False, 'Readings/Online': False,
            'Readings/NozzleValid': False, 'Readings/BedValid': False})
    _ready = True


def system_command(action):
    initialize()
    if action == 'Start':
        _write({'System/Enabled': True, 'System/Message': 'Enabled; vLock pending'})
    elif action in ('Stop', 'Reset'):
        _write({'System/Enabled': False, 'System/Message': 'Stopped; vLock pending'})
    else:
        raise ValueError('Unknown system action')
    # Supervisory state only. Never starts, cancels, or resets a printer job.


def command(action):
    if action not in ('Pause', 'Resume', 'Stop'):
        raise ValueError('Unknown printer action')
    initialize()
    _write({'Commands/' + action: True})


def _dispatch(action):
    global _latest
    if action != 'Stop' and not _busy.compareAndSet(False, True):
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
    def worker():
        try:
            response = _client.get(_url() + '/status', timeout=3000)
            if not response.good:
                raise RuntimeError('Connector unavailable')
            status = response.json
            if not status.get('online') or not status.get('mqtt_connected'):
                raise RuntimeError('Printer disconnected or telemetry stale')
            if action == 'Resume' and not _read('System/Enabled'):
                raise RuntimeError('Enable system before resuming')
            if action == 'Resume' and status.get('state') != 'Paused':
                raise RuntimeError('Resume requires a paused print')
            if action == 'Pause' and status.get('state') != 'Running':
                raise RuntimeError('Pause requires a running print')
            # Resume is distinct from Start. Older connectors reject it safely.
            response = _client.post(_url() + '/command',
                data={'action': action, 'id': request_id}, timeout=16000)
            body = response.json
            result(str(body.get('result') if response.good else body.get('error', 'Command rejected')))
        except Exception as exc:
            result('Not confirmed: ' + str(exc) + '. Check actual printer state before retrying.')
        finally:
            if action != 'Stop':
                _busy.set(False)
                _write({'Commands/Busy': False})
    system.util.invokeAsynchronous(worker)


def tick():
    if not _tick_lock.tryLock():
        return
    try:
        initialize()
        values = {'Connection/LastPoll': system.date.now(),
                  'Connection/ServiceOnline': False, 'Connection/MqttConnected': False,
                  'Connection/Message': 'Connector unavailable',
                  'Readings/Online': False, 'Readings/State': 'Offline',
                  'Readings/NozzleValid': False, 'Readings/BedValid': False}
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
                           'Readings/RawState': str(s.get('raw_state', '')) if online else ''})
            if s.get('age_seconds') is not None:
                values['Readings/AgeSeconds'] = float(s['age_seconds'])
            for field, tag, valid in [('nozzle_temp', 'NozzleTemp', 'NozzleValid'),
                                      ('bed_temp', 'BedTemp', 'BedValid')]:
                v = s.get(field)
                good = online and isinstance(v, (int, long, float)) and not isinstance(v, bool) and not math.isnan(v) and not math.isinf(v)
                values['Readings/' + valid] = good
                if good:
                    values['Readings/' + tag] = float(v)
        except Exception:
            _log.warn('Printer status unavailable; readings marked invalid')
        _write(values)
        # Consume momentary request tags once, with Stop taking precedence.
        actions = [a for a in ('Stop', 'Pause', 'Resume') if _read('Commands/' + a)]
        if actions:
            _write({'Commands/' + a: False for a in actions})
            _dispatch(actions[0])
    except Exception as exc:
        _log.error(str(exc))
    finally:
        _tick_lock.unlock()


TAGS = [{'name': 'BambuP1S', 'tagType': 'Folder', 'tags': [{'name': 'Config', 'tagType': 'Folder', 'tags': [{'name': 'ServiceUrl', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'http://127.0.0.1:8876'}]}, {'name': 'Connection', 'tagType': 'Folder', 'tags': [{'name': 'ServiceOnline', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'Message', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'Waiting for local connector'}, {'name': 'LastPoll', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'DateTime'}, {'name': 'MqttConnected', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}]}, {'name': 'Readings', 'tagType': 'Folder', 'tags': [{'name': 'Online', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'State', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'Offline'}, {'name': 'RawState', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': ''}, {'name': 'NozzleTemp', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Float8', 'value': 0}, {'name': 'BedTemp', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Float8', 'value': 0}, {'name': 'AgeSeconds', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Float8', 'value': 0}, {'name': 'NozzleValid', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'BedValid', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}]}, {'name': 'Commands', 'tagType': 'Folder', 'tags': [{'name': 'Result', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'No command requested'}, {'name': 'Pause', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'Resume', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'Stop', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'Busy', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}]}, {'name': 'System', 'tagType': 'Folder', 'tags': [{'name': 'Enabled', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'Boolean', 'value': False}, {'name': 'Message', 'tagType': 'AtomicTag', 'valueSource': 'memory', 'dataType': 'String', 'value': 'Stopped; vLock pending'}]}]}]
