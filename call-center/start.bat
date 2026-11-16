@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem Always run from the call-center folder.
cd /d "%~dp0"

title Call-Pilot - Call Center QA
set "PORT=8020"
set "VENV_PY=%~dp0..\.venv\Scripts\python.exe"

echo ============================================================
echo  Call-Pilot - AI QA for call centers
echo ============================================================
echo.

if not exist "%VENV_PY%" (
    echo Python environment not found: %VENV_PY%
    echo Run start.bat in the project root first.
    if /I not "%START_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo [1/4] Stopping the old Call-Pilot server...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_callpilot.ps1" -Port %PORT%
if errorlevel 1 goto :port_busy
echo.

if not exist "%~dp0..\.env" (
    echo WARNING: .env not found in the project root. Copy .env.example to .env.
)

echo [2/4] Checking demo audio...
if not exist "%~dp0static\audio\call_01.mp3" (
    echo Demo audio not found. Generating it with native Russian edge-tts...
    "%VENV_PY%" "%~dp0scripts\build_demo_audio.py"
    if errorlevel 1 (
        echo Audio generation failed. The UI will work without audio.
    )
) else (
    echo Demo audio found.
)
echo.

echo [3/4] Preparing demo database...
if not exist "%~dp0data\call_center.db" (
    echo Database will be created and seeded on first request.
)
echo.

echo [4/4] Starting Call-Pilot on http://127.0.0.1:%PORT%
echo.
echo Press Ctrl+C to stop the server.
echo.
if /I not "%START_NO_BROWSER%"=="1" (
    powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:%PORT%'"
)
"%VENV_PY%" -m uvicorn call_center_app:app --host 127.0.0.1 --port %PORT% --reload
echo.
echo Call-Pilot stopped.
if /I not "%START_NO_PAUSE%"=="1" pause
exit /b 0

:port_busy
echo.
echo Port %PORT% is busy. Stop the process manually or change PORT in start.bat.
if /I not "%START_NO_PAUSE%"=="1" pause
exit /b 1
