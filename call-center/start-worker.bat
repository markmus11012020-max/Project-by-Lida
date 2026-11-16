@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem Run from the project root so relative CALLPILOT_QUEUE_URL works.
cd /d "%~dp0.."

set "VENV_PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo Python environment not found: %VENV_PY%
    echo Run start.bat in the project root first.
    if /I not "%START_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo Starting Call-Pilot worker...
"%VENV_PY%" "%~dp0scripts\worker.py" %*
echo.
if /I not "%START_NO_PAUSE%"=="1" pause
