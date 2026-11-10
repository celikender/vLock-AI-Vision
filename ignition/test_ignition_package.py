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
SETTLED = '[default]vLock/A-101/Settled'


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

    def set(self, state, stop, reset, quality=good, settled=True, settled_quality=good):
        self.system.tags.update({STATE: SimpleNamespace(value=state, quality=quality),
                                 SETTLED: SimpleNamespace(value=settled, quality=settled_quality),
                                 STOP: SimpleNamespace(value=stop, quality=good),
                                 RESET: SimpleNamespace(value=reset, quality=good)})

    @staticmethod
    def run_at(seconds):
        with patch('time.time', return_value=seconds):
            return runpy.run_path(SCRIPT)

    def test_paths_match_the_tag_export(self):
        script = self.run_at(0)
        export = json.loads((HERE/'vlock-zones.json').read_text(encoding='utf-8'))
        provider, _, path = script['STATE_PATH'].partition(']')
        self.assertEqual(provider, '[default')
        tags = export['tags']
        names = path.split('/')
        for name in names[:-1]:
            tags = next((t for t in tags if t['name'] == name), {})
            if tags.get('tagType') == 'UdtInstance':
                udts = next(t for t in export['tags'] if t['name'] == '_types_')['tags']
                tags = next(t for t in udts if t['name'] == tags['typeId'])
            tags = tags.get('tags', [])
        self.assertIn(names[-1], [t['name'] for t in tags], script['STATE_PATH']+' is not in the export.')
        self.assertEqual(script['SETTLED_PATH'], script['STATE_PATH'].rsplit('/', 1)[0]+'/Settled')
        self.assertIn('Settled', [t['name'] for t in tags])
        # The integrator creates the latch's own memory tags, so an import must not overwrite them.
        for created in (script['STOP_PATH'], script['RESET_PATH']):
            self.assertEqual(created.split('/')[0], '[default]vLockExample')
            self.assertNotIn('vLockExample', [t['name'] for t in export['tags']])

    def test_active_latches_at_once_and_stays_after_clear(self):
        memory = {}
        self.assertTrue(self.evaluate(memory, True, 'Active', 0, False, False, True))
        self.assertTrue(self.evaluate(memory, True, 'Clear', 1000, True, False, True))

    def test_unknown_latches_only_after_the_debounce(self):
        memory = {}
        self.assertFalse(self.evaluate(memory, True, 'Unknown', 0, False, False, True))
        self.assertFalse(self.evaluate(memory, True, 'Unknown', 1999, False, False, True))
        self.assertTrue(self.evaluate(memory, True, 'Unknown', 2000, False, False, True))

    def test_bad_quality_counts_as_unknown_even_with_an_old_clear_value(self):
        memory = {}
        self.assertFalse(self.evaluate(memory, False, 'Clear', 0, False, False, True))
        self.assertTrue(self.evaluate(memory, False, 'Clear', 2000, False, False, True))

    def test_a_short_unknown_does_not_latch(self):
        memory = {}
        self.evaluate(memory, True, 'Unknown', 0, False, False, True)
        self.assertFalse(self.evaluate(memory, True, 'Clear', 1000, False, False, True))
        self.assertFalse(self.evaluate(memory, True, 'Unknown', 1500, False, False, True))
        self.assertFalse(self.evaluate(memory, True, 'Unknown', 3000, False, False, True))
        self.assertTrue(self.evaluate(memory, True, 'Unknown', 3500, False, False, True))

    def test_reset_only_clears_on_a_good_clear(self):
        memory = {}
        self.assertTrue(self.evaluate(memory, True, 'Active', 0, True, True, True))
        self.assertTrue(self.evaluate(memory, True, 'Unknown', 1000, True, True, True))
        self.assertTrue(self.evaluate(memory, False, 'Clear', 2000, True, True, True))
        self.assertFalse(self.evaluate(memory, True, 'Clear', 3000, True, True, True))

    def test_reset_is_refused_while_a_new_match_is_being_confirmed(self):
        memory = {}
        self.assertTrue(self.evaluate(memory, True, 'Clear', 0, True, True, False))
        self.assertFalse(self.evaluate(memory, True, 'Clear', 1000, True, True, True))
        for changes in (dict(settled=False), dict(settled_quality=bad), dict(settled=None)):
            self.system.written.clear()
            self.set('Clear', True, True, **changes)
            self.run_at(3)
            self.assertEqual(self.system.written, [{RESET: False}], changes)

    def test_count_zone_value_is_not_treated_as_safe(self):
        memory = {}
        self.evaluate(memory, True, 'Valid', 0, False, False, True)
        self.assertTrue(self.evaluate(memory, True, 'Valid', 2000, False, False, True))

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
