"""SAM worker supervisor checks with injected probes and processes; nothing is launched."""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.vision.worker_process import SamWorker, ROOT

LOADING = dict(ready=True, loaded=False, cuda=True, model_loads=0, video_window_frames=4, warmup=dict(state='loading'))
READY = dict(LOADING, loaded=True, model_loads=1, gpu_name='Test GPU', warmup=dict(state='ready', seconds=80.0))


class FakeProcess:
    def __init__(self):
        self.returncode, self.terminated = None, False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


class SamWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.launched, self.commands = [], []
        self.process = FakeProcess()

    def tearDown(self):
        self.directory.cleanup()

    def worker(self, probes):
        sequence = list(probes)

        def probe():
            return sequence.pop(0) if len(sequence) > 1 else sequence[0]

        def popen(command, **kwargs):
            self.launched.append(command)
            return self.process

        def run(command, **kwargs):
            self.commands.append(command)
            return SimpleNamespace(returncode=0, stdout='/home/tester\n')
        return SamWorker(Path(self.directory.name)/'sam.log', distro='Ubuntu', probe=probe, popen=popen, run=run,
                         poll_seconds=.01)

    def until(self, worker, state):
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            if worker.status()['state'] == state:
                return worker.status()
            time.sleep(.01)
        self.fail(f'Expected {state}, got {worker.status()}')

    def test_existing_worker_is_reused_and_never_stopped(self):
        worker = self.worker([READY])
        worker.start()
        status = self.until(worker, 'ready')
        self.assertFalse(status['owned'])
        self.assertIn('Test GPU', status['message'])
        worker.stop(wait=True)
        self.assertEqual(self.launched, [])
        self.assertFalse(any('pkill' in c for c in self.commands))

    def test_missing_worker_is_launched_from_project_root_and_stopped(self):
        worker = self.worker([None, None, LOADING, LOADING, READY])
        worker.start()
        self.until(worker, 'loading')
        self.until(worker, 'ready')
        command = self.launched[0]
        self.assertEqual(command[:7], ['wsl.exe', '-d', 'Ubuntu', '--cd', str(ROOT), '--exec',
                                       '/home/tester/.local/share/vlock-vision/sam-env/bin/python'])
        self.assertEqual(command[7:], ['-m', 'services.vision.sam_worker', '--preload'])
        self.assertTrue(worker.status()['owned'])
        worker.stop(wait=True)
        self.assertTrue(self.process.terminated)
        self.assertTrue(any('pkill' in c for c in self.commands))
        self.assertEqual(worker.status()['state'], 'stopped')

    def test_unknown_program_on_port_is_reported_not_stopped(self):
        worker = self.worker([False])
        worker.start()
        self.assertIn('another program', self.until(worker, 'blocked')['message'])
        self.assertEqual(self.launched, [])

    def test_exit_and_failed_warmup_are_reported(self):
        self.process.returncode = 1
        worker = self.worker([None, None])
        worker.start()
        self.assertIn('code 1', self.until(worker, 'failed')['message'])
        failed = self.worker([dict(READY, warmup=dict(state='failed'))])
        failed.start()
        self.assertIn('warm-up', self.until(failed, 'failed')['message'])
        missing = self.worker([dict(READY, ready=False)])
        missing.start()
        self.assertIn('weights', self.until(missing, 'failed')['message'])

    def test_restart_after_failure_launches_again(self):
        self.process.returncode = 1
        worker = self.worker([None])
        worker.start()
        self.until(worker, 'failed')
        self.process = FakeProcess()
        worker.probe = lambda: READY
        worker.restart()
        self.until(worker, 'ready')


if __name__ == '__main__':
    unittest.main()
