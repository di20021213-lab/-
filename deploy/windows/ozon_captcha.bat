@echo off
rem Open Ozon in a VISIBLE browser so you can solve the slider yourself.
rem The session is then kept in the ozon-profile folder.
rem Usage: ozon_captcha.bat "https://ozon.ru/t/XXXX"
rem Russian notes: deploy\windows\OZON.md
rem ASCII-only on purpose - see tunnel.bat for why.
cd /d "%~dp0..\.."

if not exist ".venv" (
    echo Run setup.bat first - it prepares the environment.
    pause
    exit /b 1
)

set URL=%~1
if "%URL%"=="" set URL=https://ozon.ru/t/l1ZC6Ti

echo A browser window will open. Solve the puzzle with the mouse.
.venv\Scripts\python ozon_login.py "%URL%"
pause
