@echo off
rem Run the Ozon check in a VISIBLE browser, reusing the session you solved
rem the captcha in. Headless presents a different fingerprint and gets
rem challenged again, so after ozon_captcha.bat use THIS, not ozon.bat.
rem Russian notes: deploy\windows\OZON.md
rem ASCII-only on purpose - see tunnel.bat for why.
cd /d "%~dp0..\.."

if not exist ".venv" (
    echo Run setup.bat first - it prepares the environment.
    pause
    exit /b 1
)

set OZON_HEADLESS=0
.venv\Scripts\python ozon_check.py --file ozon-links.example.txt
pause
