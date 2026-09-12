@echo off
rem Prepare the environment only: virtualenv, dependencies, browser.
rem Unlike run.bat this does not need config.yaml, so it works before the
rem backup is restored. Russian notes: deploy\windows\AFTER_INSTALL.md
rem ASCII-only on purpose - cmd.exe misparses UTF-8 Cyrillic in batch files.
cd /d "%~dp0..\.."

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install it from python.org and tick
    echo "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv || goto :fail
)

echo Installing dependencies...
.venv\Scripts\python -m pip install --quiet --upgrade pip || goto :fail
.venv\Scripts\python -m pip install --quiet -r requirements.txt || goto :fail

echo Installing the browser (about 150 MB on first run)...
.venv\Scripts\python -m playwright install chromium || goto :fail

echo.
echo Ready. Next: ozon.bat to test Ozon, or run.bat to start the bot.
pause
exit /b 0

:fail
echo.
echo Failed. Copy the last lines above - they say what went wrong.
pause
exit /b 1
