@echo off
rem StoryFX sound catalog: listen, pick or keep sounds. Opens http://127.0.0.1:8765 in the browser.
if not exist "%~dp0prototype\.venv\Scripts\python.exe" (
  echo Environment is not installed. Run: powershell -ExecutionPolicy Bypass -File "%~dp0prototype\init.ps1"
  exit /b 1
)
"%~dp0prototype\.venv\Scripts\python.exe" "%~dp0prototype\tools\catalog.py" %*
