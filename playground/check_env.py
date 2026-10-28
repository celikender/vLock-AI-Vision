"""Check local setup without sending images, exposing keys, or calling an API."""
import importlib.metadata
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    print(f"Project: {ROOT}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Interpreter: {sys.executable}")
    ready = True
    if sys.version_info < (3, 12):
        print("ERROR: Python 3.12 or later is required for this project.")
        ready = False
    for name in ("anthropic", "python-dotenv", "meta-sam-parser"):
        try:
            print(f"{name}: {importlib.metadata.version(name)}")
        except importlib.metadata.PackageNotFoundError:
            print(f"MISSING: {name}; install requirements.txt")
            ready = False
    if not ready:
        return 1

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")  # Existing shell variables take precedence.
    for name in ("ANTHROPIC_MODEL",):
        value = os.getenv(name, "claude-sonnet-5-5").strip()
        print(f"{name}: {value or 'MISSING'}")
        if not value:
            ready = False
    key_present = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    print("ANTHROPIC_API_KEY: " + ("configured (not verified)" if key_present else "MISSING; add it to the local .env"))
    ready = ready and key_present
    print("Dependencies: ready. No API requests were made.")
    print("Model configuration: " + ("ready for a live test" if ready else "incomplete"))
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())

