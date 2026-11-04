"""Muse frame-check answers expire, and an answer from a stopped or changed run is dropped."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.application import Workspace
from services.vlock.store import Store

MANIFEST = dict(TagKey='A-101', ZoneName='A', ZoneId='zone-1', OutputName='out', OutputType='condition', Rule='r',
                Object1='person', Object2='', Skill='helmet')


class StoreExpiryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.now = [1_800_000_000.0]
        self.store = Store(Path(self.directory.name)/'o.sqlite3', clock=lambda: self.now[0])

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_old_answer_reads_as_stale_and_keeps_its_time(self):
        self.store.set_zones([MANIFEST])
        self.store.set_check('zone-1', dict(VlmState='yes', VlmReason='Helmet seen.', VlmCheckedAt='then'), valid_seconds=60)
        self.now[0] += 59
        self.assertEqual(self.store.current_check('zone-1')['VlmState'], 'yes')
        self.assertEqual(self.store.zones()['zones'][0]['VlmState'], 'yes')
        self.now[0] += 1
        current = self.store.current_check('zone-1')
        self.assertEqual((current['VlmState'], current['VlmCheckedAt']), ('stale', 'then'))
        self.assertEqual(self.store.zones()['zones'][0]['VlmState'], 'stale')

    def test_new_answer_and_turning_off_reset_the_clock(self):
        self.store.set_check('zone-1', dict(VlmState='yes'), valid_seconds=60)
        self.now[0] += 61
        self.store.set_check('zone-1', dict(VlmState='no'), valid_seconds=60)
        self.assertEqual(self.store.current_check('zone-1')['VlmState'], 'no')
        self.store.set_check('zone-1', dict(VlmState='pending'))
        self.now[0] += 1000
        self.assertEqual(self.store.current_check('zone-1')['VlmState'], 'pending', 'No limit given: no expiry.')
        self.store.set_check('zone-1')
        self.assertIsNone(self.store.current_check('zone-1'))


class RunCheckTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.workspace = Workspace(self.directory.name)
        self.addCleanup(self.finish)
        self.zone = dict(id='zone-1', name='A', target='person', firstRelation='overlaps area', extraConditions=[],
                         ruleJoin='ALL (AND)', persistence=1, zone=[])
        self.skill = dict(name='Helmet', vlm=dict(question='Helmet?', answers=['yes', 'no'], interval_seconds=30))
        self.camera = SimpleNamespace(snapshot=lambda: (b'jpeg', {}))
        self.monitor = SimpleNamespace(run_id=1, revision=1, running=True)
        self.workspace.monitors['zone-1'] = self.monitor
        self.workspace.checks['zone-1'] = dict(state='Warning', busy=True, last=0)

    def finish(self):
        self.workspace.monitors.pop('zone-1', None)
        self.workspace.close()
        self.directory.cleanup()

    def answer(self, during=None):
        def check_image(*args):
            if during:
                during()
            return dict(answer='yes', reason='Helmet seen.')
        self.workspace.assistant = SimpleNamespace(check_image=check_image)
        self.workspace.run_check(self.zone, self.skill, self.camera, 'Warning')
        return self.workspace.observations.current_check('zone-1')

    def test_answer_is_published_with_a_limit(self):
        self.assertEqual(self.answer()['VlmState'], 'yes')
        self.assertIn('zone-1', self.workspace.observations.check_expiry)

    def test_answer_arriving_after_monitoring_stopped_is_dropped(self):
        self.assertIsNone(self.answer(lambda: setattr(self.monitor, 'running', False)))

    def test_answer_arriving_after_a_new_run_or_rule_is_dropped(self):
        self.assertIsNone(self.answer(lambda: setattr(self.monitor, 'run_id', 2)))
        self.assertIsNone(self.answer(lambda: setattr(self.monitor, 'revision', 2)))


if __name__ == '__main__':
    unittest.main()
