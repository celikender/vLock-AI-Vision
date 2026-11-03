"""Start, watch and stop the local SAM 3.1 worker for the application.

The worker runs in the Ubuntu WSL CUDA environment on loopback port 5052. An
already running worker is reused and never stopped by this app. An unidentified
process on 5052 is reported, never killed.
"""
import http.client
import json
import os
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
MAX_RESTARTS = 3
RESTART_WINDOW = 15 * 60
MISSED_PROBES = 3
LOG_LIMIT = 5 * 1024 * 1024
LOG_BACKUPS = 2


def probe(timeout=4):
    """Worker health, None when nothing listens, or False when 5052 is something else."""
    connection = http.client.HTTPConnection('127.0.0.1', 5052, timeout=timeout)
    try:
        # Windows retries refused loopback connections for about two seconds.
        connection.connect()
    except OSError:
        connection.close()
        return None
    try:
        connection.request('GET', '/health')
        response = connection.getresponse()
        data = json.loads(response.read(8192))
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()
    if (response.status == 200 and isinstance(data, dict) and data.get('video_window_frames') == 4
            and data.get('model_loads') is not None and isinstance(data.get('cuda'), bool)):
        return data
    return False


class SamWorker:
    def __init__(self, log_path, distro=None, probe=probe, popen=subprocess.Popen, run=subprocess.run, poll_seconds=2,
                 restart_delay=5):
        self.log_path = Path(log_path)
        self.restart_delay = restart_delay
        self.distro = distro or os.getenv('VLOCK_WSL_DISTRO', 'Ubuntu')
        self.probe, self.popen, self.run, self.poll_seconds = probe, popen, run, poll_seconds
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.process = None
        self.owned = False
        self.thread = None
        self.value = dict(state='checking', message='Checking the local SAM worker…', owned=False)

    def _set(self, state, message, **extra):
        with self.lock:
            self.value = dict(state=state, message=message, owned=self.owned, **extra)

    def status(self):
        with self.lock:
            return dict(self.value, log=str(self.log_path))

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopped.clear()
        self.thread = threading.Thread(target=self._supervise, name='sam-worker', daemon=True)
        self.thread.start()

    def restart(self):
        """Explicit retry from the UI after a failed or stopped worker."""
        # status() takes the same non-reentrant lock, so call it only after releasing it.
        with self.lock:
            running = self.value['state'] in ('starting', 'loading', 'ready')
        if running:
            return self.status()
        self.stop(wait=True)
        self.start()
        return self.status()

    def _command(self):
        python = os.getenv('SAM_PYTHON')
        if not python:
            home = self.run(['wsl.exe', '-d', self.distro, '--exec', 'printenv', 'HOME'], capture_output=True,
                            text=True, timeout=90, creationflags=NO_WINDOW)
            if home.returncode != 0 or not home.stdout.strip():
                raise OSError(f'Cannot start Ubuntu ({self.distro}) in WSL.')
            python = home.stdout.strip().rstrip('/') + '/.local/share/vlock-vision/sam-env/bin/python'
        # Separate arguments keep project paths with spaces intact.
        return ['wsl.exe', '-d', self.distro, '--cd', str(ROOT), '--exec', python, '-m',
                'services.vision.sam_worker', '--preload']

    def _launch(self):
        self._set('starting', 'Starting Ubuntu and the SAM worker…')
        command = self._command()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._rotate_log()
        log = self.log_path.open('ab')
        try:
            self.process = self.popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log,
                                      stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        finally:
            log.close()
        self.owned = True

    def _rotate_log(self):
        """Keep the worker log bounded: rotate before each launch once it passes LOG_LIMIT."""
        try:
            if not self.log_path.exists() or self.log_path.stat().st_size < LOG_LIMIT:
                return
            for index in range(LOG_BACKUPS, 0, -1):
                older = self.log_path.with_name(f'{self.log_path.name}.{index}')
                newer = self.log_path.with_name(f'{self.log_path.name}.{index - 1}') if index > 1 else self.log_path
                if newer.exists():
                    newer.replace(older)
        except OSError:
            pass  # A locked log never blocks the worker start.

    def _supervise(self):
        """Watch the worker; restart one this app started after a crash or hang, a few times at most."""
        restarts = []
        while not self.stopped.is_set():
            reason = self._watch()
            if reason is None or self.stopped.is_set():
                return
            now = time.monotonic()
            restarts = [t for t in restarts if now - t < RESTART_WINDOW]
            if len(restarts) >= MAX_RESTARTS:
                self._set('failed', reason + f' Automatic restarts stopped after {MAX_RESTARTS} tries in '
                          f'{RESTART_WINDOW // 60} minutes. See the worker log, then retry.')
                return
            restarts.append(now)
            self._set('restarting', reason + f' Restarting automatically ({len(restarts)}/{MAX_RESTARTS})…')
            self._end_process()
            if self.stopped.wait(self.restart_delay * len(restarts)):
                return

    def _watch(self):
        """Run until stopped (None), a final state (None) or a restartable failure (its reason)."""
        try:
            health = self.probe()
            if health is False:
                self._set('blocked', 'Port 5052 is used by another program. Close it, then retry. Nothing was stopped.')
                return None
            if health is None:
                self._launch()
        except (OSError, subprocess.SubprocessError) as error:
            self._set('failed', f'Could not start the SAM worker: {error}')
            return None
        began, missed, was_ready = time.monotonic(), 0, False
        while not self.stopped.is_set():
            if self.process is not None and self.process.poll() is not None:
                return f'SAM worker exited (code {self.process.returncode}).'
            health = self.probe()
            if health:
                missed = 0
                warmup = (health.get('warmup') or {}).get('state')
                if not health.get('ready'):
                    # Missing CUDA or weights: a restart cannot fix it.
                    self._set('failed', 'SAM worker is running but CUDA or the SAM 3.1 weights are unavailable.')
                    return None
                if warmup == 'failed':
                    return 'SAM warm-up failed.' if self.owned else self._final('SAM warm-up failed. See the worker log, then retry.')
                if health.get('loaded') and warmup in (None, 'ready', 'idle'):
                    was_ready = True
                    self._set('ready', 'SAM 3.1 ready on ' + (health.get('gpu_name') or 'the local GPU') + '.',
                              gpu_name=health.get('gpu_name'), warmup_seconds=(health.get('warmup') or {}).get('seconds'))
                else:
                    self._set('loading', 'Loading SAM 3.1 onto the GPU (about 1–2 minutes on first start)…')
            elif not self.owned:
                self._set('stopped', 'The external SAM worker stopped. Retry to start one from the app.')
                return None
            else:
                # One slow answer while the GPU is busy is normal; several in a row are not.
                missed += 1
                if was_ready and missed >= MISSED_PROBES:
                    return 'SAM worker stopped answering.'
                if not was_ready and time.monotonic() - began > 180:
                    return 'SAM worker did not answer within 3 minutes.'
            self.stopped.wait(self.poll_seconds)
        return None

    def _final(self, message):
        self._set('failed', message)
        return None

    def _end_process(self):
        process, self.process = self.process, None
        if process is not None and self.owned:
            process.terminate()
            # wsl.exe does not always forward termination; end only our worker module.
            try:
                self.run(['wsl.exe', '-d', self.distro, '--exec', 'pkill', '-f', 'services.vision.sam_worker'],
                         capture_output=True, timeout=15, creationflags=NO_WINDOW)
            except (OSError, subprocess.SubprocessError):
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        self.owned = False

    def stop(self, wait=False):
        self.stopped.set()
        if self.thread and wait and self.thread is not threading.current_thread():
            self.thread.join(timeout=5)
        self._end_process()
        self._set('stopped', 'SAM worker stopped.')
