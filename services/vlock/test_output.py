"""Capture-age and known/unknown observation publication contract checks."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services.vlock.store import Store
from services.vlock.output import ObservationOutput


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.directory.name)/'state.sqlite3')
        self.zone=dict(id='zone_a',name='Dog zone',output='dog_detected',outputType='condition')
        self.config=dict(sam_prompt='dog',validity_seconds=1)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def signal(self):
        return self.store.snapshot()['assets'][0]['signals'][0]

    def test_capture_age_and_expiry_are_not_renewed_by_publication(self):
        output=ObservationOutput(self.store,self.zone)
        output.send(self.config,'Warning','Dog in zone',time.monotonic()-.5,count=1)
        signal=self.signal()
        self.assertEqual(signal['status'],'active')
        self.assertEqual(signal['source_id'],'vision')
        self.store.clock=lambda:time.time()+.6
        self.assertEqual(self.signal()['status'],'stale')
        self.assertIsNone(self.store.snapshot()['assets'][0]['inhibit'])

    def test_valid_zero_is_distinct_from_missing_or_old_count(self):
        zone=self.zone|dict(output='dog_count',outputType='count')
        output=ObservationOutput(self.store,zone)
        output.send(self.config,'Normal','No dogs',time.monotonic(),count=0)
        self.assertEqual(self.signal()['value'],0)
        self.assertEqual(self.signal()['status'],'valid')
        output.send(self.config,'Unknown','Frame missing')
        self.assertIsNone(self.signal()['value'])
        self.assertEqual(self.signal()['status'],'unknown')
        output.send(self.config,'Normal','Old result',time.monotonic()-2,count=0)
        self.assertEqual(self.signal()['status'],'unknown')

    def test_storage_failure_is_reported_without_claiming_delivery(self):
        output=ObservationOutput(self.store,self.zone)
        with patch.object(self.store,'submit',side_effect=OSError('Storage unavailable')):
            output.send(self.config,'Warning','Detection',time.monotonic())
        self.assertEqual(output.status['state'],'error')
        self.assertIsNone(output.status['last_sent_at'])

    def test_event_output_preserves_state_without_establishing_inhibit(self):
        output=ObservationOutput(self.store,self.zone|dict(output='dog_event',outputType='event'))
        output.send(self.config,'Warning','Rule event',time.monotonic())
        asset=self.store.snapshot()['assets'][0]
        self.assertIsNone(asset['inhibit'])
        self.assertEqual(asset['signals'][0]['value'],{'state':'Warning'})
        self.assertEqual(asset['signals'][0]['kind'],'measurement')


if __name__=='__main__':
    unittest.main()
