@echo off
REM Windows launcher (ASCII only, no BOM)
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo venv not found. Please run setup.bat first.
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python app.py
endlocal
