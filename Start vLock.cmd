@echo off
title vLock-AI Vision
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. See docs\SETUP.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" web\application.py --open
if errorlevel 1 pause
