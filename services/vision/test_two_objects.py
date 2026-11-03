"""Two-object zone rules: per-object geometry on the same frame, ALL/ANY, fail-closed."""
import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from services.vision.configuration import Store, validate
from services.vision.monitoring import Monitoring
from services.vision.test_monitoring import config, jpeg, result
from services.vision.zone_rules import RuleState, evaluate_all, targets


def two(join='all', condition='mask_overlaps_zone'):
    value = config()
    value['second'] = {'prompt': 'dog', 'condition': condition}
    value['rule']['join'] = join
    return value


def empty(index=0, prompt='dog'):
    row = result(index=index, prompt=prompt)
    row.update(objects=[], count=0)
    return row


class TwoObjectRuleTests(unittest.TestCase):
    def test_and_needs_both_objects_on_the_same_frame(self):
        self.assertEqual(targets(two()), [('person', 'mask_overlaps_zone'), ('dog', 'mask_overlaps_zone')])
        matched, details, outcomes = evaluate_all([result(), result(prompt='dog')], two())
        self.assertTrue(matched)
        self.assertEqual(outcomes, [True, True])
        self.assertEqual({d['concept'] for d in details}, {'person', 'dog'})
        matched, _, outcomes = evaluate_all([result(), empty()], two())
        self.assertFalse(matched)
        self.assertEqual(outcomes, [True, False])

    def test_or_needs_either_object(self):
        self.assertTrue(evaluate_all([empty(prompt='person'), result(prompt='dog')], two('any'))[0])
        self.assertFalse(evaluate_all([empty(prompt='person'), empty()], two('any'))[0])

    def test_each_object_uses_its_own_condition(self):
        # person overlaps AND dog absent: an empty dog result satisfies the second condition.
        self.assertTrue(evaluate_all([result(), empty()], two(condition='object_absent'))[0])
        self.assertFalse(evaluate_all([result(), result(prompt='dog')], two(condition='object_absent'))[0])

    def test_missing_or_mismatched_object_results_never_clear(self):
        for results in ([result()], [result(), None]):
            with self.subTest(results=len(results)), self.assertRaises(ValueError):
                evaluate_all(results, two('any'))
        other = result(index=1, prompt='dog')
        with self.assertRaises(ValueError):
            evaluate_all([result(), other], two())

    def test_stale_combined_observation_is_unknown(self):
        state = RuleState(0, stale_seconds=10)
        state.observe(False, time.monotonic()-20)
        self.assertEqual(state.state, 'Unknown')

    def test_saved_one_object_files_load_and_second_object_validates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'monitor.json'
            saved = config()
            del saved['second']
            del saved['rule']['join']
            path.write_text(json.dumps(saved), encoding='utf-8')
            loaded = Store(path).load()
            self.assertIsNone(loaded['second'])
            self.assertEqual(loaded['rule']['join'], 'all')
        self.assertEqual(validate(two('any'), two('any'))['second'], {'prompt': 'dog', 'condition': 'mask_overlaps_zone'})
        for bad in [dict(prompt='person', condition='mask_overlaps_zone'), dict(prompt='dog', condition='crosses'),
                    dict(prompt='', condition='mask_overlaps_zone'), 'dog']:
            value = two()
            value['second'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate(value, value)
        value = two()
        value['rule']['join'] = 'xor'
        with self.assertRaises(ValueError):
            validate(value, value)
        cleared = two()
        cleared['second'] = None
        self.assertIsNone(validate(cleared, two())['second'], 'An explicit None removes the second object')


class TwoObjectMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        counter = [0]

        def fetch(camera):
            counter[0] += 1
            return jpeg(), {'X-Frame-Sequence': str(counter[0]), 'X-Frame-Age-Ms': '0'}
        self.monitor = Monitoring(fetch=fetch, path=Path(self.directory.name)/'configuration.json')
        self.monitor.connect({'camera': config()['camera']})
        self.monitor.save(two())

    def tearDown(self):
        self.monitor.stop()
        if self.monitor.thread:
            self.monitor.thread.join(3)
        self.directory.cleanup()

    def run_windows(self, infer, until):
        self.monitor.infer = infer
        self.monitor.start()
        deadline = time.monotonic()+6
        while time.monotonic() < deadline and not until():
            time.sleep(.02)
        self.monitor.stop()
        self.monitor.thread.join(3)

    def test_one_prompt_per_object_on_the_same_frames(self):
        calls = []

        def infer(frames, prompt, revision):
            calls.append((prompt, [f['sequence'] for f in frames]))
            for index, frame in enumerate(frames):
                row = result(index=index, prompt=prompt, revision=revision)
                row['frame_sequence'] = frame['sequence']
                yield row
        self.run_windows(infer, lambda: len(calls) >= 2 and self.monitor.output_id >= 4)
        self.assertEqual([c[0] for c in calls[:2]], ['person', 'dog'])
        self.assertEqual(calls[0][1], calls[1][1], 'Both prompts see the same camera frames')
        row = self.monitor.frames[-1]
        self.assertEqual(row['counts'], {'person': 1, 'dog': 1})
        self.assertEqual(row['object_matches'], {'person': True, 'dog': True})
        self.assertIsInstance(row['check_seconds'], float)
        self.assertEqual({o['concept'] for o in row['objects']}, {'person', 'dog'})

    def test_failure_of_either_object_reports_unknown(self):
        calls = []

        def infer(frames, prompt, revision):
            calls.append(prompt)
            if prompt == 'dog':
                raise OSError('Injected worker loss for the second object')
            for index, frame in enumerate(frames):
                row = result(index=index, prompt=prompt, revision=revision)
                row['frame_sequence'] = frame['sequence']
                yield row
        self.run_windows(infer, lambda: 'dog' in calls)
        self.assertEqual(self.monitor.output_id, 0, 'Nothing is published from a half-finished check')
        self.assertEqual(self.monitor.status()['state'], 'Unknown')

    def test_incomplete_second_object_stream_reports_unknown(self):
        seen = threading.Event()

        def infer(frames, prompt, revision):
            for index, frame in enumerate(frames):
                if prompt == 'dog' and index == 2:
                    seen.set()
                    return
                row = result(index=index, prompt=prompt, revision=revision)
                row['frame_sequence'] = frame['sequence']
                yield row
        self.run_windows(infer, seen.is_set)
        self.assertEqual(self.monitor.output_id, 0)
        self.assertEqual(self.monitor.status()['state'], 'Unknown')


if __name__ == '__main__':
    unittest.main()
