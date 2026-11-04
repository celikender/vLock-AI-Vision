"""Reference Gateway Timer script: raise a latched fault when the vLock heartbeat stops.

Install in the Designer: Gateway Events > Timer, fixed delay 1000 ms, then paste this file.
Create two Boolean Memory tags first:
    [default]vLock/Bridge/WatchdogFault
    [default]vLock/Bridge/WatchdogReset
The HeartbeatCounter tag comes from the vLock UDT import (see ZONE_TAGS.md).

The script only sets WatchdogFault. It sends no machine command: the integrator decides what
the fault does. A fault clears only when an operator sets WatchdogReset while the heartbeat
is moving, so a returning heartbeat never resumes anything by itself.

Not yet run in a real Ignition gateway; only the logic has automated tests.
"""
import time

COUNTER_PATH = "[default]vLock/Bridge/HeartbeatCounter"
FAULT_PATH = "[default]vLock/Bridge/WatchdogFault"
RESET_PATH = "[default]vLock/Bridge/WatchdogReset"
STALE_MS = 3000


def evaluate(state, good, counter, now_ms, fault, reset):
    """The next fault value. A Bad or unchanged counter does not count as a heartbeat."""
    if good and counter != state.get("counter"):
        state["counter"] = counter
        state["changed_at"] = now_ms
    state.setdefault("changed_at", now_ms)
    if now_ms - state["changed_at"] > STALE_MS:
        return True
    return False if reset else fault


def run_watchdog():
    logger = system.util.getLogger("vLockHeartbeatWatchdog")
    state = system.util.getGlobals().setdefault("vLockHeartbeatWatchdog", {})
    counter, fault, reset = system.tag.readBlocking([COUNTER_PATH, FAULT_PATH, RESET_PATH])
    was_faulted = fault.value == True
    reset_requested = reset.quality.isGood() and reset.value == True
    faulted = evaluate(state, counter.quality.isGood(), counter.value, int(time.time() * 1000),
                       was_faulted, reset_requested)
    writes = []
    if faulted != was_faulted or not fault.quality.isGood():
        writes.append((FAULT_PATH, faulted))
        if faulted:
            logger.warn("vLock heartbeat stale for more than %d ms." % STALE_MS)
    if reset_requested:
        writes.append((RESET_PATH, False))
    if writes:
        system.tag.writeBlocking([path for path, _ in writes], [value for _, value in writes])


run_watchdog()
