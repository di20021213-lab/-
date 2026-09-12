@echo off
rem Build avito-watcher.exe. RUN THIS ON WINDOWS: PyInstaller only produces a
rem Windows exe on Windows, it cannot cross-compile from Linux.
rem Output: dist\avito-watcher\ - copy the whole folder anywhere, no Python needed.
rem Russian notes: deploy\windows\README.md
rem ASCII-only on purpose - see tunnel.bat for why.
cd /d "%~dp0..\.."

if not exist ".venv" (
    echo Run run.bat first - it sets up the environment and the browser.
    pause
    exit /b 1
)

.venv\Scripts\python -m pip install --quiet pyinstaller || goto :fail

echo Building...
.venv\Scripts\python -m PyInstaller --noconfirm --clean ^
    --name avito-watcher ^
    --collect-all playwright ^
    --collect-all dotenv ^
    --hidden-import yaml ^
    deploy\windows\entry.py || goto :fail

rem Put the browser next to the exe: paths.py picks it up from there, so the
rem folder can be copied to a machine with no Playwright installed.
echo Copying the browser next to the exe...
set "PLAYWRIGHT_BROWSERS_PATH=%CD%\dist\avito-watcher\browsers"
.venv\Scripts\python -m playwright install chromium || goto :fail

copy config.yaml dist\avito-watcher\ >nul 2>nul
copy .env dist\avito-watcher\ >nul 2>nul

echo.
echo Done: dist\avito-watcher\avito-watcher.exe
echo config.yaml and .env must sit next to the exe - copy them if the lines
echo above did not.
pause
exit /b 0

:fail
echo.
echo Build failed. The last lines above explain why.
pause
exit /b 1
