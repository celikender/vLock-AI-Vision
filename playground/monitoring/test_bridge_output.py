"""Synthetic perception through the real local bridge API; no camera or machine calls."""
import copy
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'playground'/'segmentation'))
sys.path.insert(0, str(ROOT/'playground'/'vlock_bridge'))
from playground.monitoring.bridge_output import BridgeOutput
from playground.monitoring.configuration import DEFAULT, validate
from playground.monitoring.controller import Monitoring
from store import Store
from server import make_server
from test_monitoring import config, result, jpeg


class BridgeOutputTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name)/'bridge.sqlite3')
        self.server = make_server(self.store, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.publisher = BridgeOutput(self.server.server_port)
        self.config = copy.deepcopy(DEFAULT)
        self.config['bridge']['enabled'] = True

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.store.close(); self.directory.cleanup()

    def signals(self):
        return {s['signal_id']: s for s in self.store.snapshot()['assets'][0]['signals']}

    def test_fresh_count_rule_clear_unknown_and_expiry(self):
        self.publisher.send(self.config, 'Warning', 'Zone confirmed', time.monotonic()-2, 2)
        self.assertEqual(self.publisher.status['state'], 'sent')
        signals = self.signals()
        self.assertEqual(signals['people_count']['value'], 2)
        self.assertEqual(signals['zone_condition']['status'], 'active')
        # Freshness is anchored to capture, not when the HTTP call finished.
        self.assertGreater(time.time()-__import__('datetime').datetime.fromisoformat(signals['people_count']['observed_at']).timestamp(), 1.9)
        self.publisher.send(self.config, 'Normal', 'Confirmed absent', time.monotonic(), 0)
        self.assertEqual(self.signals()['people_count']['value'], 0)
        self.assertEqual(self.signals()['zone_condition']['status'], 'clear')
        self.store.clock = lambda: time.time()+11
        self.assertEqual(self.signals()['people_count']['status'], 'stale')
        self.store.clock = time.time
        self.publisher.send(self.config, 'Unknown', 'Camera lost')
        self.assertEqual(self.signals()['people_count']['status'], 'unknown')
        self.assertEqual(self.signals()['zone_condition']['status'], 'unknown')

    def test_disabled_old_frame_and_pending_confirmation(self):
        self.config['bridge']['enabled'] = False
        self.publisher.send(self.config, 'Warning', 'Ignored', time.monotonic(), 1)
        self.assertEqual(self.store.snapshot()['assets'], [])
        self.config['bridge']['enabled'] = True
        self.publisher.send(self.config, 'Warning', 'Too old', time.monotonic()-20, 1)
        self.assertEqual(self.signals()['people_count']['status'], 'unknown')
        self.publisher.send(self.config, 'Unknown', 'Confirming', time.monotonic(), 1)
        self.assertEqual(self.signals()['people_count']['status'], 'valid')
        self.assertEqual(self.signals()['zone_condition']['status'], 'unknown')

    def test_network_failure_reported_without_fabricating_clear(self):
        with patch('playground.monitoring.bridge_output.http.client.HTTPConnection') as factory:
            factory.return_value.request.side_effect = OSError('private diagnostic')
            self.publisher.send(self.config, 'Normal', 'Test', time.monotonic(), 0)
        self.assertEqual(self.publisher.status['state'], 'error')
        self.assertNotIn('private', self.publisher.status['message'])
        self.assertEqual(self.store.snapshot()['assets'], [])

    def test_controller_confirmation_and_stop_publish_to_bridge(self):
        monitor = Monitoring(None, path=Path(self.directory.name)/'monitor.json')
        value = config(); value['bridge']['enabled'] = True
        monitor.save(value); monitor.bridge = self.publisher
        before = time.monotonic()-1
        with patch('playground.monitoring.controller.render', return_value='test-overlay'):
            for i in range(2):
                monitor.publish(result(index=i), {'jpeg':jpeg(), 'captured_at':before+i*.1}, 0, value)
        self.assertEqual(self.signals()['zone_condition']['status'], 'active')
        self.assertEqual(self.signals()['people_count']['value'], 1)
        monitor.running = True
        monitor.stop()
        self.assertEqual(self.signals()['zone_condition']['status'], 'unknown')
        self.assertEqual(self.signals()['people_count']['status'], 'unknown')
        self.assertEqual({s['source_id'] for s in self.signals().values()}, {'sam'})

    def test_old_configuration_migrates_disabled_and_wrong_target_rejected(self):
        old = copy.deepcopy(DEFAULT); old.pop('bridge')
        self.assertFalse(validate(old, old)['bridge']['enabled'])
        self.config['sam_prompt'] = 'forklift'
        with self.assertRaises(ValueError): validate(self.config)


if __name__ == '__main__':
    unittest.main()
