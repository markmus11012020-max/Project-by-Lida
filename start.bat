@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem Always run from the project root.
cd /d "%~dp0"

title LLM Process Automation MVP
set "PORT=8030"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PYTHON=python"

echo ============================================================
echo  LLM Process Automation MVP - start
echo ============================================================
echo.

echo [1/5] Stopping the old server...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_server.ps1" -Port %PORT%
if errorlevel 1 goto :port_busy
echo.

echo [2/5] Clearing Python cache...
for /d /r "%~dp0app" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
for /d /r "%~dp0tests" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
for /d /r "%~dp0scripts" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
if exist "%~dp0.pytest_cache" rd /s /q "%~dp0.pytest_cache"
if exist "%~dp0.ruff_cache" rd /s /q "%~dp0.ruff_cache"
if exist "%~dp0.mypy_cache" rd /s /q "%~dp0.mypy_cache"
echo Cache cleared. Database and results are preserved.
echo.

echo [3/5] Checking Python...
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python not found. Install Python 3.10+ and add it to PATH.
        goto :error
    )
    set "PYTHON=py -3"
)

echo [4/5] Preparing virtual environment and dependencies...
if not exist "%VENV_PY%" (
    echo Creating .venv...
    %PYTHON% -m venv "%~dp0.venv"
    if errorlevel 1 goto :error
)
if not exist "%~dp0.env" (
    copy /y "%~dp0.env.example" "%~dp0.env" >nul
    echo Created .env from .env.example. Insert a real AITUNNEL_API_KEY.
)
findstr /C:"AITUNNEL_API_KEY=sk-your-key-here" "%~dp0.env" >nul 2>nul
if not errorlevel 1 (
    echo WARNING: .env still contains the placeholder API key. Live requests will not work.
)
"%VENV_PY%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 goto :error
echo.

echo [5/5] Starting the new server...
echo.
echo API:    http://127.0.0.1:%PORT%/docs
echo Health: http://127.0.0.1:%PORT%/health
echo.
echo Press Ctrl+C to stop the server.
echo.
"%VENV_PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% --reload
echo.
echo Server stopped.
if /I not "%START_NO_PAUSE%"=="1" pause
exit /b 0

:port_busy
echo.
echo Port %PORT% is busy. Stop the process manually or change PORT in start.bat.
if /I not "%START_NO_PAUSE%"=="1" pause
exit /b 1

:error
echo.
echo Startup failed. Check the messages above.
if /I not "%START_NO_PAUSE%"=="1" pause
exit /b 1
