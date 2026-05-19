@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

cd /d "%~dp0"

set "VENV_DIR=%~dp0.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "BASE_PYTHON="

if not exist "requirements.txt" (
    echo requirements.txt was not found in %CD%.
    pause
    exit /b 1
)

if not exist "%VENV_PYTHON%" (
    echo Creating local Python virtual environment...
    call :find_python
    if not defined BASE_PYTHON (
        echo Python 3.10 or newer was not found. Install Python from https://www.python.org/downloads/ and run this file again.
        pause
        exit /b 1
    )
    !BASE_PYTHON! -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

echo Checking Python dependencies...
"%VENV_PYTHON%" -m ensurepip --upgrade >nul 2>&1
"%VENV_PYTHON%" -m pip --disable-pip-version-check install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies from requirements.txt.
    pause
    exit /b 1
)

echo Launching WebUI...
"%VENV_PYTHON%" -m app web --host 127.0.0.1 --port 7860 %*
if errorlevel 1 (
    echo WebUI exited with an error.
    pause
    exit /b 1
)

exit /b 0

:find_python
py -3.10 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "BASE_PYTHON=py -3.10"
    exit /b 0
)

py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "BASE_PYTHON=py -3"
    exit /b 0
)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "BASE_PYTHON=python"
    exit /b 0
)

exit /b 0
