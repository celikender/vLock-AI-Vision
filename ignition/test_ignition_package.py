"""The Ignition package: export matches the app's generator; example latch logic, outside Ignition."""
import builtins
import json
import runpy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from services.vlock import zone_tags

SCRIPT = str(HERE/'stop_latch_example.py')
RULE = 'Treat Unknown or Bad quality as stop; latch/reset is integrator responsibility.'
good = SimpleNamespace(isGood=lambda: True)
bad = SimpleNamespace(isGood=lambda: False)
STATE, STOP, RESET = ('[default]vLock/A-101/State', '[default]vLockExample/A-101/StopRequest',
                      '[default]vLockExample/A-101/StopReset')


class PackageTests(unittest.TestCase):
    def test_export_matches_the_app_generator(self):
        expected = zone_tags.ignition_export([dict(TagKey='A-101')])
        self.assertEqual(json.loads((HERE/'vlock-zones.json').read_text(encoding='utf-8')), expected)

    def test_contract_has_the_rule_and_every_state(self):
        text = (HERE/'INTEGRATION.md').read_text(encoding='utf-8')
        self.assertIn(RULE, text)
        for state in ('`Active`', '`Clear`', '`Valid`', '`Unknown`', 'HeartbeatCounter'):
            self.assertIn(state, text)

    def test_contract_reasons_match_the_code(self):
        text = (HERE/'INTEGRATION.md').read_text(encoding='utf-8')
        monitoring = (HERE.parent/'services/vision/monitoring.py').read_text(encoding='utf-8')
        meta = (HERE.parent/'services/vision/meta_sam.py').read_text(encoding='utf-8')
        for reason, source in (('Camera unavailable. Check the camera connection.', monitoring),
                               ('Local SAM unavailable. Check the GPU worker.', monitoring),
                               ('Meta SAM unavailable. Check the internet connection and the API key.', meta)):
            self.assertIn(reason, text)
            self.assertIn(reason, source)

    def test_script_says_it_is_an_example(self):
        self.assertTrue(Path(SCRIPT).read_text(encoding='utf-8').startswith('"""EXAMPLE ONLY'))


class FakeSystem:
    def __init__(self):
        self.globals, self.tags, self.written = {}, {}, []
        self.tag = SimpleNamespace(readBlocking=lambda paths: [self.tags[path] for path in paths], writeBlocking=self.write)
        self.util = SimpleNamespace(getGlobals=lambda: self.globals)

    def write(self, paths, values):
        self.written.append(dict(zip(paths, values)))
        for path, value in zip(paths, values):
            self.tags[path] = SimpleNamespace(value=value, quality=good)


class ExampleLatchTests(unittest.TestCase):
    def setUp(self):
        self.system = FakeSystem()
        builtins.system = self.system
        self.addCleanup(lambda: delattr(builtins, 'system'))
        self.set('Clear', False, False)
        self.evaluate = self.run_at(0)['evaluate']

    def set(self, state, stop, reset, quality=good):
        self.system.tags.update({STATE: SimpleNamespace(value=state, quality=quality),
                                 STOP: SimpleNamespace(value=stop, quality=good),
                                 RESET: SimpleNamespace(value=reset, quality=good)})

    @staticmethod
    def run_at(seconds):
        with patch('time.time', return_value=seconds):
            return runpy.run_path(SCRIPT)

    def test_active_latches_at_once_and_stays_after_clear(self):
        memory = {}
        self.assertTrue(self.evaluate(memory, True, 'Active', 0, False, False))
        self.assertTrue(self.evaluate(memory, True, 'Clear', 1000, True, False))

    def test_unknown_latches_only_after_the_debounce(self):
        memory = {}
        self.assertFalse(self.evaluate(memory, True, 'Unknown', 0, False, False))
        self.assertFalse(self.evaluate(memory, True, 'Unknown', 1999, False, False))
        self.assertTrue(self.evaluate(memory, True, 'Unknown', 2000, False, False))

    def test_bad_quality_counts_as_unknown_even_with_an_old_clear_value(self):
        memory = {}
        self.assertFalse(self.evaluate(memory, False, 'Clear', 0, False, False))
        self.assertTrue(self.evaluate(memory, False, 'Clear', 2000, False, False))

    def test_a_short_unknown_does_not_latch(self):
        memory = {}
        self.evaluate(memory, True, 'Unknown', 0, False, False)
        self.assertFalse(self.evaluate(memory, True, 'Clear', 1000, False, False))
        self.assertFalse(self.evaluate(memory, True, 'Unknown', 1500, False, False))
        self.assertFalse(self.evaluate(memory, True, 'Unknown', 3000, False, False))
        self.assertTrue(self.evaluate(memory, True, 'Unknown', 3500, False, False))

    def test_reset_only_clears_on_a_good_clear(self):
        memory = {}
        self.assertTrue(self.evaluate(memory, True, 'Active', 0, True, True))
        self.assertTrue(self.evaluate(memory, True, 'Unknown', 1000, True, True))
        self.assertTrue(self.evaluate(memory, False, 'Clear', 2000, True, True))
        self.assertFalse(self.evaluate(memory, True, 'Clear', 3000, True, True))

    def test_count_zone_value_is_not_treated_as_safe(self):
        memory = {}
        self.evaluate(memory, True, 'Valid', 0, False, False)
        self.assertTrue(self.evaluate(memory, True, 'Valid', 2000, False, False))

    def test_script_writes_only_on_change_and_clears_the_reset_tag(self):
        self.system.written.clear()
        self.run_at(1)
        self.assertEqual(self.system.written, [])
        self.set('Active', False, False)
        self.run_at(2)
        self.assertEqual(self.system.written, [{STOP: True}])
        self.system.written.clear()
        self.set('Clear', True, True)
        self.run_at(3)
        self.assertEqual(self.system.written, [{STOP: False, RESET: False}])


if __name__ == '__main__':
    unittest.main()
