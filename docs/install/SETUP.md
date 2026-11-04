# Python environment setup

Run these commands in a PowerShell terminal from the project folder:

```powershell
cd "C:\Users\ec-en\Desktop\vLock-AI Vision"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Most people should follow the [install guide](INSTALL.md); this page is the short version for developers.
Add your Meta API key on the app's Setup page, or copy .env.example to .env and fill it in. Never commit
or paste the key into a chat. META_MUSE_MODEL defaults to muse-spark-1.3.

The local SAM 3.1 worker runs in a separate Ubuntu/WSL CUDA environment; set it up
once with [SAM runtime](SAM_RUNTIME.md). Then double-click `Start vLock.cmd`.
