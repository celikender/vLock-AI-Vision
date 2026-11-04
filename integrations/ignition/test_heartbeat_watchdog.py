"""Heartbeat watchdog logic and tag writes, run outside Ignition with a stand-in for its system module."""
import builtins
import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = str(Path(__file__).with_name('heartbeat_watchdog.py'))
good = SimpleNamespace(isGood=lambda: True)
bad = SimpleNamespace(isGood=lambda: False)


class FakeSystem:
    def __init__(self):
        self.globals = {}
        self.tags = {}
        self.written = []
        self.tag = SimpleNamespace(readBlocking=self.read, writeBlocking=self.write)
        self.util = SimpleNamespace(getGlobals=lambda: self.globals,
                                    getLogger=lambda name: SimpleNamespace(warn=lambda message: None))

    def read(self, paths):
        return [self.tags[path] for path in paths]

    def write(self, paths, values):
        self.written.append(dict(zip(paths, values)))
        for path, value in zip(paths, values):
            self.tags[path] = SimpleNamespace(value=value, quality=good)


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.system = FakeSystem()
        builtins.system = self.system
        self.addCleanup(lambda: delattr(builtins, 'system'))
        self.paths = ['[default]vLock/Bridge/' + name for name in ('HeartbeatCounter', 'WatchdogFault', 'WatchdogReset')]
        self.set(1, False, False)
        self.evaluate = self.run_at(0)['evaluate']

    def set(self, counter, fault, reset, quality=good):
        self.system.tags.update({
            self.paths[0]: SimpleNamespace(value=counter, quality=quality),
            self.paths[1]: SimpleNamespace(value=fault, quality=good),
            self.paths[2]: SimpleNamespace(value=reset, quality=good)})

    @staticmethod
    def run_at(seconds):
        with patch('time.time', return_value=seconds):
            return runpy.run_path(SCRIPT)

    def test_moving_heartbeat_is_healthy(self):
        state = {}
        for second in range(10):
            self.assertFalse(self.evaluate(state, True, second, second*1000, False, False))

    def test_stopped_heartbeat_faults_after_three_seconds(self):
        state = {}
        self.assertFalse(self.evaluate(state, True, 5, 0, False, False))
        self.assertFalse(self.evaluate(state, True, 5, 3000, False, False))
        self.assertTrue(self.evaluate(state, True, 5, 3001, False, False))

    def test_bad_quality_is_not_a_heartbeat(self):
        state = {}
        self.evaluate(state, True, 5, 0, False, False)
        self.assertTrue(self.evaluate(state, False, 6, 4000, False, False))

    def test_a_counter_never_seen_faults_too(self):
        state = {}
        self.assertFalse(self.evaluate(state, False, None, 0, False, False))
        self.assertTrue(self.evaluate(state, False, None, 4000, False, False))

    def test_fault_stays_latched_until_reset_while_healthy(self):
        state = {}
        self.evaluate(state, True, 1, 0, False, False)
        self.assertTrue(self.evaluate(state, True, 1, 4000, False, False))
        self.assertTrue(self.evaluate(state, True, 2, 5000, True, False), 'A returning heartbeat does not clear it.')
        self.assertTrue(self.evaluate(state, True, 2, 9000, True, True), 'Reset cannot clear a stale heartbeat.')
        self.assertFalse(self.evaluate(state, True, 3, 10000, True, True))

    def test_script_writes_only_on_change_and_clears_the_reset_tag(self):
        self.system.written.clear()
        self.run_at(1)
        self.assertEqual(self.system.written, [], 'Healthy: no writes.')
        self.run_at(5)
        self.assertEqual(self.system.written, [{self.paths[1]: True}])
        self.system.written.clear()
        self.set(2, True, True)
        self.run_at(6)
        self.assertEqual(self.system.written, [{self.paths[1]: False, self.paths[2]: False}])


if __name__ == '__main__':
    unittest.main()
