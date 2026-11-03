# Python environment setup

Run these commands in a PowerShell terminal from the project folder:

```powershell
cd "C:\Users\ec-en\Desktop\vLock-AI Vision"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

If .env does not exist yet, copy .env.example to .env and set META_API_KEY to your
Meta developer key (Muse Spark rule proposals). Never commit or paste the key into
a chat. META_MUSE_MODEL defaults to muse-spark-1.3. The ANTHROPIC_* settings belong
to the retired photo experiment and are not used by the application.

The local SAM 3.1 worker runs in a separate Ubuntu/WSL CUDA environment; set it up
once with [SAM runtime](SAM_RUNTIME.md). Then double-click `Start vLock.cmd`.
