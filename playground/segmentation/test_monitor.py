import threading
import time
import unittest
from monitor import Presence, Monitor, two_hands_moved


class PresenceTests(unittest.TestCase):
    def test_motion_emits_named_event_after_two_comparisons(self):
        sequence = [0]
        def fetch(address):
            sequence[0] += 1
            return b'jpeg', {'X-Frame-Sequence':str(sequence[0]),'X-Frame-Age-Ms':'0'}
        def infer(*args):
            y = 0.2 + min(sequence[0], 4) * 0.06
            return {'count':2,'detections':[{'center':[0.2,y],'area':0.1},
                                           {'center':[0.8,y],'area':0.1}]}
        monitor = Monitor(fetch=fetch, infer=infer)
        monitor.start('192.168.1.50', 'ignored', 'two_hands_moving')
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                events = monitor.status()['events']
                if any(e['type'] == 'two_hands_moving' for e in events):
                    break
                time.sleep(0.05)
            self.assertEqual(sum(e['type']=='two_hands_moving' for e in events), 1)
            self.assertEqual(monitor.prompt, 'hand')
        finally:
            monitor.stop()
            monitor.thread.join(2)

    def test_two_hand_motion_pairing(self):
        before = [[0.2,0.3],[0.8,0.3]]
        self.assertTrue(two_hands_moved(before, [[0.8,0.4],[0.2,0.4]]))
        self.assertFalse(two_hands_moved(before, before[::-1]))
        self.assertFalse(two_hands_moved(before, [[0.2,0.4],[0.8,0.3]]))
        self.assertFalse(two_hands_moved(before, [[0.2,0.4]]))
        self.assertFalse(two_hands_moved(None, before))

    def setUp(self):
        self.now = 100
        self.state = Presence(clock=lambda: self.now)

    def test_confirm_and_debounce(self):
        self.assertFalse(self.state.observe(1, 100))
        self.assertTrue(self.state.observe(1, 100))
        self.assertEqual(self.state.state, 'present')
        self.assertFalse(self.state.observe(0, 100))
        self.assertFalse(self.state.observe(1, 100))
        self.assertEqual(self.state.state, 'present')
        self.state.observe(0, 100)
        self.assertTrue(self.state.observe(0, 100))
        self.assertEqual(self.state.state, 'absent')

    def test_stale_and_failure_never_mean_absent(self):
        self.state.observe(1, 100)
        self.state.observe(1, 100)
        self.now = 111
        self.assertTrue(self.state.expire())
        self.assertEqual(self.state.state, 'unknown')
        self.state.observe(0, 100)
        self.assertEqual(self.state.state, 'unknown')
        self.state.observe(0, 111)
        self.state.unavailable('disconnected')
        self.state.observe(0, 111)
        self.assertEqual(self.state.state, 'unknown')

    def test_bad_counts_rejected(self):
        for count in (None, True, -1, 9, '1'):
            with self.assertRaises(ValueError):
                self.state.observe(count, 100)

    def test_stop_discards_inflight_result_and_blocks_restart(self):
        entered, release = threading.Event(), threading.Event()
        def infer(*args):
            entered.set()
            release.wait(3)
            return {'count': 1}
        monitor = Monitor(fetch=lambda address: (b'jpeg', {'X-Frame-Sequence':'1','X-Frame-Age-Ms':'0'}), infer=infer)
        monitor.start('192.168.1.50', 'person')
        try:
            self.assertTrue(entered.wait(2))
            monitor.stop()
            with self.assertRaises(ValueError):
                monitor.start('192.168.1.50', 'cup')
        finally:
            release.set()
            monitor.thread.join(3)
        state = monitor.status()
        self.assertFalse(state['running'])
        self.assertIsNone(state['result'])
        self.assertEqual([e['type'] for e in state['events']], ['started', 'stopped'])

    def test_duplicate_frame_does_not_confirm(self):
        calls = []
        def infer(*args):
            calls.append(1)
            return {'count':1}
        monitor = Monitor(fetch=lambda address: (b'jpeg', {'X-Frame-Sequence':'1','X-Frame-Age-Ms':'0'}), infer=infer)
        monitor.start('192.168.1.50', 'person')
        time.sleep(0.6)
        monitor.stop()
        monitor.thread.join(2)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('present', [e['type'] for e in monitor.status()['events']])


if __name__ == '__main__':
    unittest.main()
