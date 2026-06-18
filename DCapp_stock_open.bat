@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "APP_URL=http://127.0.0.1:8080"
set "PYTHON_EXE=.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
  set "PYTHON_EXE=python"
)

echo Starting DCapp Stock...
echo URL: %APP_URL%
echo Python: %PYTHON_EXE%
echo Output: this window
echo.
echo Keep this window open while using the app.
echo Press Ctrl+C to stop the app.
echo.

set "RUN_ON_STARTUP=0"
if not exist "logs" mkdir "logs"
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process '%APP_URL%'"

"%PYTHON_EXE%" -u app.py

echo.
echo App stopped. If there is an error above, copy the last few lines.
pause
