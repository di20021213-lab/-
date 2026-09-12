@echo off
rem Start the bot on Windows. Double-click this file.
rem First run installs dependencies and the browser (about 5 minutes).
rem Russian instructions: deploy\windows\AFTER_INSTALL.md
rem
rem ASCII-only on purpose: cmd.exe misparses UTF-8 Cyrillic in batch files.
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

echo Checking dependencies...
.venv\Scripts\python -m pip install --quiet --upgrade pip || goto :fail
.venv\Scripts\python -m pip install --quiet -r requirements.txt || goto :fail
.venv\Scripts\python -m playwright install chromium || goto :fail

if not exist "config.yaml" (
    echo.
    echo config.yaml is missing. Copy config.multiregion.example.yaml to
    echo config.yaml, and put your token and chat_id into .env
    pause
    exit /b 1
)

echo.
echo Running. Keep this window open - the bot works while it is.
echo Stop with Ctrl+C
echo.
.venv\Scripts\python -m avito_watcher.main %*
pause
exit /b 0

:fail
echo.
echo Failed. Copy the last lines above - they say what went wrong.
pause
exit /b 1
