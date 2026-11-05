@echo off
rem StoryFX launcher, works from any folder. Example: run.cmd --mode kids
if not exist "%~dp0prototype\.venv\Scripts\python.exe" (
  echo Environment is not installed. Run: powershell -ExecutionPolicy Bypass -File "%~dp0prototype\init.ps1"
  exit /b 1
)
"%~dp0prototype\.venv\Scripts\python.exe" -m storyfx %*
