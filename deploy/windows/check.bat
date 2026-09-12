@echo off
rem One-off check: what the bot sees and how the filters worked.
rem Sends nothing, writes nothing to the database.
rem ASCII-only on purpose - see tunnel.bat for why.
cd /d "%~dp0..\.."
if not exist ".venv" (
    echo Run run.bat first - it sets up the environment.
    pause
    exit /b 1
)
.venv\Scripts\python -m avito_watcher.main --check
pause
