@echo off
rem Check whether Ozon lets our browser through, using the links in
rem ozon-links.example.txt. Sends nothing anywhere, just reports.
rem Russian notes: deploy\windows\OZON.md
rem ASCII-only on purpose - see tunnel.bat for why.
cd /d "%~dp0..\.."

if not exist ".venv" (
    echo Run setup.bat first - it prepares the environment.
    pause
    exit /b 1
)

.venv\Scripts\python ozon_check.py --file ozon-links.example.txt
pause
