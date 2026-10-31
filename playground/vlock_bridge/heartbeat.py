"""A periodic application heartbeat, independent of HTTP reads or observations."""
import threading
import time

from store_time import utc


class Heartbeat:
    def __init__(self, interval_seconds=1, monotonic=time.monotonic, clock=time.time, autostart=True):
        if not 0 < interval_seconds <= 60:
            raise ValueError('Heartbeat interval must be positive and at most 60 seconds.')
        self.interval = interval_seconds
        self.timeout = max(5, interval_seconds * 3)
        self.monotonic = monotonic
        self.clock = clock
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.counter = 0
        self.pulse = False
        self.beat()
        self.thread = threading.Thread(target=self.run, daemon=True) if autostart else None
        if self.thread:
            self.thread.start()

    def beat(self):
        with self.lock:
            self.counter += 1
            self.pulse = not self.pulse
            self.changed_at = self.monotonic()
            self.timestamp = utc(self.clock())

    def run(self):
        while not self.stopped.wait(self.interval):
            self.beat()

    def snapshot(self):
        with self.lock:
            return dict(online=not self.stopped.is_set() and self.monotonic() - self.changed_at < self.timeout,
                heartbeat=self.timestamp, heartbeat_counter=self.counter, heartbeat_pulse=self.pulse,
                heartbeat_interval_seconds=self.interval, offline_after_seconds=self.timeout)

    def close(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=2)
