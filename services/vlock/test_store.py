"""Deterministic contract, persistence, concurrency and local HTTP integration checks."""
import concurrent.futures
import http.client
import json
import os
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from services.vlock.store import BridgeError, Store, utc
from services.vlock.heartbeat import Heartbeat


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'bridge.sqlite3'
        self.now = 1800000000.0
        self.store = Store(self.path, clock=lambda: self.now)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def sample(self, **changes):
        return dict(asset_id='conveyor_01', source_id='manual', signal_id='zone_01',
                    status='active', reason='Simulated presence', ttl_seconds=30) | changes

    def output(self):
        return self.store.snapshot()['assets'][0]

    def test_active_clear_unknown_are_distinct(self):
        self.assertEqual(self.store.snapshot()['assets'], [])
        for index, (status, inhibit) in enumerate([('active', True), ('clear', False), ('unknown', None)]):
            self.now += 1
            self.store.submit(self.sample(status=status))
            self.assertIs(self.output()['inhibit'], inhibit)
            self.assertEqual(self.output()['observation_status'], status)
            self.assertEqual(self.store.snapshot()['revision'], index + 1)

    def test_sources_and_signals_cannot_clear_each_other(self):
        self.store.submit(self.sample(source_id='camera_01'))
        self.store.submit(self.sample(status='clear'))
        self.assertTrue(self.output()['inhibit'])
        self.assertEqual(len(self.output()['signals']), 2)
        self.store.submit(self.sample(signal_id='zone_02', status='unknown'))
        self.assertTrue(self.output()['inhibit'])
        self.assertEqual(self.output()['quality'], 'uncertain')

    def test_measurement_does_not_create_an_inhibit(self):
        self.store.submit(self.sample(kind='measurement', status='valid', value={'count': 12}))
        asset = self.output()
        self.assertIsNone(asset['inhibit'])
        self.assertEqual(asset['signals'][0]['value'], {'count': 12})
        self.store.submit(self.sample(signal_id='presence', status='clear'))
        self.assertIs(self.output()['inhibit'], False)

    def test_heartbeat_is_independent_of_observations_wall_clock_and_revision(self):
        self.store.close()
        elapsed = [100.]
        heartbeat = Heartbeat(monotonic=lambda: elapsed[0], autostart=False)
        self.store = Store(self.path, clock=lambda: self.now, heartbeat=heartbeat)
        self.assertEqual(self.store.snapshot()['heartbeat_counter'], 1)
        self.now += 1000
        self.assertEqual(self.store.snapshot()['heartbeat_counter'], 1)
        elapsed[0] += 2.9
        state = self.store.snapshot()
        self.assertEqual(state['heartbeat_counter'], 1, 'Reading elapsed time must not manufacture a beat.')
        heartbeat.beat()
        self.assertEqual(self.store.snapshot()['heartbeat_counter'], 2)
        self.assertEqual(state['revision'], 0)
        self.store.submit(self.sample())
        self.now += 31
        state = self.store.snapshot()
        self.assertTrue(state['online'])
        self.assertEqual(state['heartbeat_counter'], 2)
        self.assertIsNone(state['assets'][0]['inhibit'])
        self.assertEqual(state['offline_after_seconds'], 5)

    def test_heartbeat_ticks_and_toggles_without_api_reads(self):
        heartbeat = Heartbeat(interval_seconds=.02)
        try:
            initial = heartbeat.snapshot()
            time.sleep(.08)
            later = heartbeat.snapshot()
            self.assertGreater(later['heartbeat_counter'], initial['heartbeat_counter'])
            self.assertIs(later['heartbeat_pulse'], later['heartbeat_counter'] % 2 == 1)
        finally:
            heartbeat.close()
        self.assertFalse(heartbeat.snapshot()['online'])

    def test_retention_bounds_history_and_observation_bodies(self):
        self.store.close()
        self.store = Store(self.path, clock=lambda: self.now, history_limit=5)
        for index in range(12):
            self.now += 1
            self.store.submit(self.sample(observation_id=f'event_{index}', value=index))
        self.assertEqual([event['revision'] for event in self.store.events()], [8, 9, 10, 11, 12])
        self.assertEqual(self.store.history_info(), dict(retention_limit=5, stored_count=5, oldest_revision=8))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0], 5)
        self.assertEqual(self.store.snapshot()['revision'], 12)
        self.assertTrue(self.store.submit(self.sample(observation_id='event_11', value=11))['duplicate'])

    def test_retention_preserves_current_signal_and_its_duplicate_protection(self):
        self.store.close()
        self.store = Store(self.path, clock=lambda: self.now, history_limit=5)
        original = self.sample(observation_id='current_old')
        self.store.submit(original)
        for index in range(8):
            self.now += 1
            self.store.submit(self.sample(signal_id='other', value=index))
        self.assertEqual(len(self.store.events()), 5)
        self.assertEqual(len(self.output()['signals']), 2)
        self.assertTrue(self.store.submit(original)['duplicate'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0], 6)

    def test_existing_event_table_migrates_and_prunes_without_resetting_revision(self):
        import sqlite3
        path = Path(self.directory.name) / 'legacy.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('''CREATE TABLE events (revision INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT, created_at TEXT, asset_id TEXT, payload TEXT)''')
            for _ in range(12):
                db.execute("INSERT INTO events(event_type,created_at,payload) VALUES('legacy','2026-10-30T00:00:00Z','{}')")
        db.close()
        migrated = Store(path, history_limit=5)
        try:
            self.assertEqual(len(migrated.events()), 5)
            self.assertEqual(migrated.snapshot()['revision'], 12)
            self.assertIn('observation_id', {r['name'] for r in migrated.db.execute('PRAGMA table_info(events)')})
        finally:
            migrated.close()

    def test_expiry_cannot_clear_an_active_condition_and_records_once(self):
        self.store.submit(self.sample(ttl_seconds=2))
        self.now += 2
        self.assertIsNone(self.output()['inhibit'])
        self.assertEqual(self.output()['observation_status'], 'stale')
        self.assertEqual([e['event_type'] for e in self.store.events()], ['observation', 'expired'])
        self.assertEqual(self.store.snapshot()['revision'], 2)

    def test_stale_clear_and_explicit_unknown_are_not_clear(self):
        self.store.submit(self.sample(status='clear'))
        self.now += 31
        self.assertIsNone(self.output()['inhibit'])
        self.store.submit(self.sample(source_id='other', status='unknown'))
        self.assertEqual(self.output()['observation_status'], 'unknown')

    def test_restart_preserves_history_but_requires_fresh_input(self):
        self.store.submit(self.sample(status='clear'))
        self.store.close()
        self.store = Store(self.path, clock=lambda: self.now)
        self.assertIsNone(self.output()['inhibit'])
        self.assertEqual(self.output()['signals'][0]['unavailable_reason'], 'restart')
        self.assertEqual(len(self.store.events()), 2)
        self.now += 1
        self.store.submit(self.sample(status='clear'))
        self.assertIs(self.output()['inhibit'], False)

    def test_duplicate_is_idempotent_and_never_refreshes_expiry(self):
        sample = self.sample(observation_id='request_01', ttl_seconds=2)
        first = self.store.submit(sample)
        self.now += 3
        second = self.store.submit(sample)
        self.assertTrue(second['duplicate'])
        self.assertEqual(first['observation'], second['observation'])
        self.assertIsNone(self.output()['inhibit'])
        with self.assertRaises(BridgeError) as conflict:
            self.store.submit(sample | {'status': 'clear'})
        self.assertEqual(conflict.exception.status, 409)

    def test_old_duplicate_cannot_replace_a_new_observation(self):
        old = self.sample(observation_id='old')
        self.store.submit(old)
        self.now += 1
        self.store.submit(self.sample(status='clear'))
        self.store.submit(old)
        self.assertIs(self.output()['inhibit'], False)

    def test_timestamp_ordering_future_expiry_and_kind_changes(self):
        self.store.submit(self.sample(observed_at=utc(self.now)))
        for change, expected in [({'observed_at': utc(self.now)}, 409),
                                 ({'observed_at': utc(self.now - 1)}, 409),
                                 ({'observed_at': utc(self.now + 5)}, 422),
                                 ({'observed_at': utc(self.now - 31)}, 422),
                                 ({'kind': 'measurement', 'status': 'valid', 'value': 5}, 409)]:
            with self.subTest(change=change), self.assertRaises(BridgeError) as error:
                self.store.submit(self.sample(**change))
            self.assertEqual(error.exception.status, expected)
        self.assertTrue(self.output()['inhibit'])
        self.assertEqual(len(self.store.events()), 1)

    def test_invalid_inputs_leave_no_history(self):
        invalid = [[], self.sample(asset_id='../outside'), self.sample(status=False),
                   self.sample(ttl_seconds=True), self.sample(ttl_seconds=0),
                   self.sample(ttl_seconds=10**500), self.sample(ttl_seconds=float('inf')),
                   self.sample(value=float('nan')), self.sample(details=[]),
                   self.sample(observed_at='2026-10-30T10:00:00'),
                   self.sample(kind='measurement', status='valid'), self.sample(extra='typo')]
        for sample in invalid:
            with self.subTest(sample=sample), self.assertRaises(BridgeError):
                self.store.submit(sample)
        self.assertEqual(self.store.events(), [])

    def test_parallel_duplicate_writes_only_once(self):
        sample = self.sample(observation_id='shared_request')
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: self.store.submit(sample), range(16)))
        self.assertEqual(sum(not r['duplicate'] for r in results), 1)
        self.assertEqual(len(self.store.events()), 1)

    def test_history_cursor_can_replay_without_skipping(self):
        for index in range(5):
            self.now += 1
            self.store.submit(self.sample(value=index))
        recent = self.store.events(limit=2)
        self.assertEqual([e['revision'] for e in recent], [4, 5])
        self.assertEqual([e['revision'] for e in self.store.events(after=0, limit=2)], [1, 2])
        page = self.store.events(after=1, limit=2)
        self.assertEqual([e['revision'] for e in page], [2, 3])
        self.assertEqual([e['revision'] for e in self.store.events(after=3)], [4, 5])
