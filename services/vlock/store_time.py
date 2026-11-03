"""Shared UTC serialization and a steady clock for observations and application heartbeats."""
import time
from datetime import datetime, timezone

_WALL_AT_START = time.time()
# perf_counter is monotonic with sub-microsecond resolution; monotonic() ticks only every
# ~15.6 ms on Windows, which made two quick results look out of order.
_COUNTER_AT_START = time.perf_counter()


def steady_now():
    """Wall-clock seconds that never jump: the start time plus elapsed high-resolution time.

    Observation order and expiry use this clock, so an NTP step or a manual PC clock
    change after start can neither freeze an old Clear nor reject fresh results.
    Timestamps may drift from a corrected PC clock until the next application start.
    """
    return _WALL_AT_START + (time.perf_counter() - _COUNTER_AT_START)


def utc(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
