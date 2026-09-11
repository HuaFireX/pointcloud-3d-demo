@echo off
REM Windows setup: create venv + install dependencies (ASCII only, no BOM)
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment .venv ...
    py -3.12 -m venv .venv 2>nul
    if errorlevel 1 py -3.11 -m venv .venv 2>nul
    if errorlevel 1 py -3.10 -m venv .venv 2>nul
    if errorlevel 1 python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo Failed to create venv. Please install Python 3.10-3.12 and retry.
        exit /b 1
    )
) else (
    echo [1/3] .venv already exists, skip creation
)

echo [2/3] Upgrading pip ...
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip

echo [3/3] Installing dependencies ...
pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed.
    exit /b 1
)

echo.
echo Setup done. Run run.bat to start the demo.
endlocal
