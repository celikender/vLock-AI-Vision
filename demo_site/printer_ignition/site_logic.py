"""Customer-side Gateway logic. Runs in Ignition Jython 2.7, not in vLock."""
from java.lang import System as Clock
from java.util import UUID
from java.util.concurrent.locks import ReentrantLock

_lock = ReentrantLock()
_ready = False
_session = str(UUID.randomUUID())
_epoch = 0
_heartbeat = {}
_bad_since = None
_pause_pending = False
_was_clear = False


def _now():
    return Clock.nanoTime() / 1000000.0


def initialize():
    global _ready
    if not _ready:
        bambuP1s.initialize()
        bambuP1s._write({'System/Enabled': False, 'System/ResetValid': False,
            'System/CanReset': False, 'System/ResumeAllowed': False,
            'System/HeartbeatMoving': False, 'System/Message': 'Reset, then System Start required'})
        _ready = True


def _sample():
    """Read original qualified source tags, never the diagnostic mirror."""
    global _bad_since, _epoch, _was_clear
    now = _now()
    _heartbeat.setdefault('changed', now)
    state, reason, all_good, online, counter_good, counter = 'Unknown', 'Vision tags unavailable', False, False, False, None
    settled = False
    try:
        zone = str(bambuP1s._read('Config/VisionZonePath')).rstrip('/')
        if not zone.startswith('[default]vLock/') or '/' in zone[len('[default]vLock/'):]:
            raise ValueError('Use a fixed zone folder')
        values = system.tag.readBlocking([zone + '/State', zone + '/Quality', zone + '/Reason',
            '[default]vLock/Bridge/Online', '[default]vLock/Bridge/HeartbeatCounter', zone + '/Settled'], 1000)
        sq, qq, rq, oq, cq, tq = values
        state = str(sq.value) if sq.quality.isGood() else 'Unknown'
        reason = str(rq.value)[:250] if rq.quality.isGood() else 'Reason tag quality is Bad'
        online = oq.quality.isGood() and oq.value == True
        counter_good = cq.quality.isGood() and isinstance(cq.value, (int, long)) and not isinstance(cq.value, bool)
        counter = cq.value if counter_good else None
        all_good = all(q.quality.isGood() for q in values[:5]) and str(qq.value) == 'Good' and counter_good
        # State changes after two matching checks. Settled is False as soon as one fresh check disagrees.
        settled = tq.quality.isGood() and tq.value == True
    except Exception:
        pass
    if counter_good and online:
        if not _heartbeat.get('seen'):
            _heartbeat.update(seen=True, counter=counter)
        elif counter != _heartbeat.get('counter'):
            _heartbeat.update(counter=counter, changed=now, moving=True)
    else:
        _heartbeat.update(seen=False, moving=False)
    frozen = now - _heartbeat['changed'] > 5000
    moving = bool(_heartbeat.get('moving') and not frozen and counter_good and online)
    clear = all_good and online and moving and state == 'Clear' and settled
    if _was_clear and not clear:
        _epoch += 1  # A transient outage must not release an old Resume when Clear returns.
    _was_clear = clear
    unavailable = not all_good or not online or state not in ('Active', 'Clear')
    if not unavailable:
        _bad_since = None
    return dict(now=now, state=state, reason=reason, clear=clear, moving=moving,
                frozen=frozen, unavailable=unavailable)


def _running():
    try:
        return bambuP1s._read('Readings/Online') == True and bambuP1s._read('Readings/State') == 'Running'
    except Exception:
        return False


def _latched():
    try:
        return bambuP1s._read('System/StopLatched') == True
    except Exception:
        return True


def _latch(reason):
    global _epoch, _pause_pending
    if _latched():
        return False
    _epoch += 1
    bambuP1s._write({'System/StopLatched': True, 'System/ResetValid': False,
        'System/Enabled': False, 'System/ResumeAllowed': False, 'Commands/Resume': False,
        'System/StopReason': reason, 'System/Message': 'Stop latched: ' + reason})
    bambuP1s._event('Stop latched: ' + reason)
    _pause_pending = True
    _try_pause()
    return True


def _try_pause():
    global _pause_pending
    if _pause_pending and _running():
        _pause_pending = False  # One attempt per latch; no automatic retry after an unknown result.
        bambuP1s.command('Pause')


def tick():
    global _bad_since
    if not _lock.tryLock():
        return
    try:
        initialize()
        sample = _sample()
        if sample['state'] == 'Active':
            _latch('Vision Active: ' + sample['reason'])
        if sample['unavailable']:
            if _bad_since is None:
                _bad_since = sample['now']
            if sample['now'] - _bad_since >= 2000:
                _latch('Vision Unknown, unavailable or Bad quality for 2 seconds: ' + sample['reason'])
        else:
            _bad_since = None
        if sample['frozen']:
            _latch('Vision heartbeat unchanged for over 5 seconds')
        _try_pause()
        allowed = (sample['clear'] and not _latched() and bambuP1s._read('System/Enabled') == True
                   and bambuP1s._read('System/ResetValid') == True)
        bambuP1s._write({'System/CanReset': sample['clear'], 'System/HeartbeatMoving': sample['moving'],
                         'System/ResumeAllowed': allowed})
    except Exception as exc:
        system.util.getLogger('PrinterSite').error('Site logic unavailable: ' + str(exc))
        try:
            bambuP1s._write({'System/ResumeAllowed': False, 'System/CanReset': False})
        except Exception:
            pass
    finally:
        _lock.unlock()


def system_command(action):
    global _epoch, _pause_pending
    _lock.lock()
    try:
        initialize()
        if action == 'Stop':
            fresh = _latch('Operator System Stop')
            if not fresh:
                _epoch += 1
                bambuP1s._write({'System/Enabled': False, 'System/ResetValid': False,
                    'System/ResumeAllowed': False, 'Commands/Resume': False})
                _pause_pending = True
                _try_pause()
            return 'System Stop latched; Pause requested only for a Running printer'
        sample = _sample()
        if action == 'Reset':
            if not sample['clear']:
                raise ValueError('Reset refused: require a settled Clear, Good quality, Online and a moving heartbeat')
            _epoch += 1
            _pause_pending = False
            bambuP1s._write({'System/StopLatched': False, 'System/ResetValid': True,
                'System/Enabled': False, 'System/ResumeAllowed': False, 'Commands/Resume': False,
                'System/StopReason': '', 'System/Message': 'Reset complete; System Start then operator Resume'})
            return 'Latch reset; printer unchanged; System Start then Resume separately'
        if action == 'Start':
            if not sample['clear'] or _latched() or bambuP1s._read('System/ResetValid') != True:
                raise ValueError('Start refused: a valid Reset and current Clear vision are required')
            _epoch += 1
            bambuP1s._write({'System/Enabled': True, 'System/ResumeAllowed': True,
                            'System/Message': 'Enabled; Resume requires an operator click'})
            return 'System enabled; no printer command sent'
        raise ValueError('Unknown system action')
    finally:
        _lock.unlock()


def resume_token():
    _lock.lock()
    try:
        initialize()
        if not _sample()['clear'] or _latched() or bambuP1s._read('System/ResetValid') != True or bambuP1s._read('System/Enabled') != True:
            raise ValueError('Resume inhibited; require Clear vision, Reset and System Start')
        return _session + ':' + str(_epoch)
    finally:
        _lock.unlock()


def check_resume(token):
    if token is None or token != resume_token():
        raise ValueError('Resume request expired; press Resume again after valid Reset and Start')
