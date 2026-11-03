"""Read-only, bounded hardware and existing worker diagnostics off the HTTP path."""
import copy
import http.client
import json
import shutil
import subprocess
import threading
import time


class Diagnostics:
    def __init__(self):
        self.lock=threading.Lock()
        self.stopped=threading.Event()
        self.value=dict(state='checking',worker={},hardware={})
        self.thread=threading.Thread(target=self._loop,name='vision-diagnostics',daemon=True)
        self.thread.start()

    def _loop(self):
        try:
            import psutil
            psutil.cpu_percent()
        except ImportError:
            psutil=None
        gpu_tool=shutil.which('nvidia-smi')
        while not self.stopped.is_set():
            worker={}
            connection=http.client.HTTPConnection('127.0.0.1',5052,timeout=1)
            try:
                connection.request('GET','/health')
                response=connection.getresponse()
                data=json.loads(response.read(8192))
                if response.status==200:
                    worker={k:data.get(k) for k in ('ready','loaded','cuda','model_loads','video_window_frames')}
                    worker['reachable']=True
            except (OSError,ValueError,http.client.HTTPException):
                worker={'reachable':False}
            finally:
                connection.close()
            hardware={}
            if psutil:
                hardware.update(cpu_percent=psutil.cpu_percent(),memory_percent=psutil.virtual_memory().percent)
            if gpu_tool:
                try:
                    result=subprocess.run([gpu_tool,'--query-gpu=name,utilization.gpu,memory.used,memory.total',
                        '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=2,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    if result.returncode==0:
                        name,usage,used,total=result.stdout.splitlines()[0].split(',')
                        hardware.update(gpu_name=name.strip(),gpu_percent=float(usage),gpu_memory_mb=float(used),gpu_memory_total_mb=float(total))
                except (OSError,ValueError,IndexError,subprocess.TimeoutExpired):
                    pass
            with self.lock:
                self.value=dict(state='sampled',worker=worker,hardware=hardware,sampled_at=time.time())
            self.stopped.wait(5)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.value)

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=3.5)
