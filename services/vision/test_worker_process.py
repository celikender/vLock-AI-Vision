"""SAM worker supervisor checks with injected probes and processes; nothing is launched."""
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
        self.exit_code = None

    def tearDown(self):
        self.directory.cleanup()

    def worker(self, probes):
        sequence = list(probes)

        def probe():
            return sequence.pop(0) if len(sequence) > 1 else sequence[0]

        def popen(command, **kwargs):
            self.launched.append(command)
            # Each launch gets its own process; exit_code makes every new one exit at once.
            self.process = FakeProcess()
            self.process.returncode = self.exit_code
            return self.process

        def run(command, **kwargs):
            self.commands.append(command)
            return SimpleNamespace(returncode=0, stdout='/home/tester\n')
        return SamWorker(Path(self.directory.name)/'sam.log', distro='Ubuntu', probe=probe, popen=popen, run=run,
                         poll_seconds=.01, restart_delay=.01)

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

    def test_crash_is_restarted_automatically_then_gives_up(self):
        self.exit_code = 1
        worker = self.worker([None])
        worker.start()
        status = self.until(worker, 'failed')
        self.assertIn('code 1', status['message'])
        self.assertIn('Automatic restarts stopped after 3 tries', status['message'])
        self.assertEqual(len(self.launched), 4, 'First launch plus three automatic restarts')
        self.assertTrue(any('pkill' in c for c in self.commands), 'A crashed worker is cleaned up before relaunch')

    def test_hung_worker_is_restarted_and_recovers(self):
        answers = iter([None, READY, None, None, None, None])
        worker = self.worker([None])
        worker.probe = lambda: next(answers, READY)
        worker.start()
        self.until(worker, 'ready')
        deadline = time.monotonic() + 2
        while len(self.launched) < 2 and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(len(self.launched), 2, 'Three missed probes after ready restart the worker')
        self.until(worker, 'ready')
        worker.stop(wait=True)

    def test_missing_weights_and_external_failures_are_not_restarted(self):
        missing = self.worker([dict(READY, ready=False)])
        missing.start()
        self.assertIn('weights', self.until(missing, 'failed')['message'])
        failed = self.worker([dict(READY, warmup=dict(state='failed'))])
        failed.start()
        self.assertIn('warm-up', self.until(failed, 'failed')['message'])
        self.assertEqual(self.launched, [], 'Workers this app did not start are never relaunched')

    def test_external_worker_is_awaited_and_never_launched(self):
        answers = iter([None, None, READY, READY, None, None, READY])
        worker = self.worker([None])
        worker.launch = False
        worker.probe = lambda: next(answers, READY)
        worker.start()
        self.assertIn('container', self.until(worker, 'starting')['message'])
        self.until(worker, 'ready')
        self.until(worker, 'starting')
        self.until(worker, 'ready')
        self.assertEqual(self.launched, [], 'Docker mode never starts WSL')
        worker.stop(wait=True)

    def test_log_is_rotated_before_launch(self):
        from services.vision import worker_process
        log = Path(self.directory.name)/'sam.log'
        log.write_bytes(b'x' * (worker_process.LOG_LIMIT + 1))
        worker = self.worker([None, READY])
        worker.start()
        self.until(worker, 'ready')
        self.assertTrue((Path(self.directory.name)/'sam.log.1').exists())
        self.assertLess(log.stat().st_size if log.exists() else 0, worker_process.LOG_LIMIT)
        worker.stop(wait=True)

    def test_log_stays_bounded_while_a_running_process_writes_to_it(self):
        from services.vision import worker_process
        folder = Path(self.directory.name)
        chunks = iter([b'x'*400]*10+[b'last line\n', b''])
        with patch.object(worker_process, 'LOG_LIMIT', 1000):
            self.worker([])._copy_log(SimpleNamespace(read=lambda size: next(chunks)))
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ['sam.log', 'sam.log.1', 'sam.log.2'])
        self.assertEqual((folder/'sam.log').read_bytes(), b'x'*400+b'last line\n')
        self.assertEqual((folder/'sam.log.1').stat().st_size, 1200)

    def test_output_of_a_real_process_reaches_the_log(self):
        writer = "import sys\nsys.stdout.buffer.write(b'from the worker\\n');sys.stdout.buffer.flush()\n"
        process = subprocess.Popen([sys.executable, '-c', writer], stdout=subprocess.PIPE, bufsize=0)
        self.worker([])._copy_log(process.stdout)
        process.wait(10)
        process.stdout.close()
        self.assertEqual((Path(self.directory.name)/'sam.log').read_bytes().replace(b'\r\n', b'\n'), b'from the worker\n')

    def test_worker_output_goes_through_the_app_and_keeps_draining_on_log_errors(self):
        worker = self.worker([])
        worker.log_path = Path(self.directory.name)  # A folder: every write fails.
        stream = BytesIO(b'a'*70000)
        worker._copy_log(stream)
        self.assertEqual(stream.read(), b'', 'All output was read, so the worker can never block on a full pipe.')

    def test_restart_after_failure_launches_again(self):
        self.exit_code = 1
        worker = self.worker([None])
        worker.start()
        self.until(worker, 'failed')
        self.exit_code = None
        worker.probe = lambda: READY
        worker.restart()
        self.until(worker, 'ready')

    def test_restart_while_running_returns_status_without_relaunch(self):
        worker = self.worker([READY])
        worker.start()
        self.until(worker, 'ready')
        result = []
        caller = threading.Thread(target=lambda: result.append(worker.restart()), daemon=True)
        caller.start()
        caller.join(1)
        self.assertFalse(caller.is_alive(), 'restart() blocked while the worker was ready')
        self.assertEqual(result[0]['state'], 'ready')
        self.assertEqual(self.launched, [])
        self.assertEqual(worker.status()['state'], 'ready')
        worker.stop(wait=True)


if __name__ == '__main__':
    unittest.main()
