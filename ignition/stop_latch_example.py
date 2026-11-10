"""EXAMPLE ONLY: one way an integrator could latch a stop request from vLock zone status.

Not a safety function and not part of the product. vLock-AI Vision only publishes status;
latch/reset is integrator responsibility. Review and adapt this before any use. It has only been
run outside Ignition with a stand-in for the system module, never in a real gateway.

Install in the Designer: Gateway Events > Timer, fixed delay 1000 ms, then paste this file.
Create two Boolean Memory tags first, and edit the paths below for your zone:
    [default]vLockExample/A-101/StopRequest
    [default]vLockExample/A-101/StopReset

For rule zones (State Active or Clear), not count zones. It sets StopRequest only and sends no machine
command: map StopRequest to your own permissive. Clearing it never restarts anything by itself.
Also watch the heartbeat: a frozen app can leave its last State in place (see INTEGRATION.md).
"""
import time

STATE_PATH = "[default]vLock/A-101/State"
SETTLED_PATH = "[default]vLock/A-101/Settled"
STOP_PATH = "[default]vLockExample/A-101/StopRequest"
RESET_PATH = "[default]vLockExample/A-101/StopReset"
DEBOUNCE_MS = 2000  # How long Unknown or Bad quality may last before it latches.


def evaluate(memory, good, state, now_ms, latched, reset, settled):
    """The next StopRequest. Anything but a good Active or Clear counts as Unknown.

    A reset needs a settled Clear: State changes only after two matching checks, so Settled is
    False as soon as one fresh check disagrees with it."""
    if good and state == "Active":
        memory.pop("unknown_since", None)
        return True
    if good and state == "Clear":
        memory.pop("unknown_since", None)
        return False if reset and settled else latched
    since = memory.setdefault("unknown_since", now_ms)
    return True if now_ms - since >= DEBOUNCE_MS else latched


def run_example():
    memory = system.util.getGlobals().setdefault("vLockStopLatchExample", {})
    state, stop, reset, settled = system.tag.readBlocking([STATE_PATH, STOP_PATH, RESET_PATH, SETTLED_PATH])
    was_latched = stop.value == True
    reset_requested = reset.quality.isGood() and reset.value == True
    latched = evaluate(memory, state.quality.isGood(), state.value, int(time.time() * 1000),
                       was_latched, reset_requested, settled.quality.isGood() and settled.value == True)
    writes = []
    if latched != was_latched or not stop.quality.isGood():
        writes.append((STOP_PATH, latched))
    if reset_requested:
        writes.append((RESET_PATH, False))  # A refused reset must be requested again.
    if writes:
        system.tag.writeBlocking([path for path, _ in writes], [value for _, value in writes])


run_example()
