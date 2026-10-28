# Python environment setup

Run these commands in VS Code's PowerShell terminal from the project folder:

```powershell
cd "C:\Users\ec-en\Desktop\vLock-AI Vision"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If .env does not exist yet, copy .env.example to .env. Set ANTHROPIC_API_KEY in .env to
your Anthropic API key. Never commit or paste the key into a chat.
The active photo-analysis client uses ANTHROPIC_API_KEY and optional ANTHROPIC_MODEL (default claude-sonnet-5-5).
Meta settings in .env.example are reserved for later SAM/Muse experiments.

```powershell
.\.venv\Scripts\python.exe playground/check_env.py
.\.venv\Scripts\python.exe -m pip check
```

The checker prints package versions, the interpreter path, model identifiers, and
whether a key is present. It never prints the key and makes no network requests.
Exit code 0 means locally configured, 1 means runtime/dependencies need attention,
and 2 means configuration is incomplete. A configured key is not proof of valid
credentials or model access; that requires a separate live request.

In VS Code, use Python: Select Interpreter and choose .venv\Scripts\python.exe
if the Python extension is installed. Explicit commands above work without
activating the environment or changing PowerShell execution policy.

## Current scope

The camera playground serves a browser-local camera and sends a captured JPEG and
optional question to Anthropic Claude only when Analyze is clicked. See
playground/camera/README.md for the full flow and offline tests.
No local CUDA inference or SAM request is implemented.

Reference: https://platform.claude.com/docs/en/build-with-claude/vision

