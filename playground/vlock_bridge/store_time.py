"""Shared UTC serialization for observations and application heartbeats."""
from datetime import datetime, timezone


def utc(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
