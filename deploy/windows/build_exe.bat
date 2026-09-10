@echo off
chcp 65001 >nul
rem Собирает avito-watcher.exe. ЗАПУСКАТЬ НА WINDOWS: PyInstaller делает exe
rem только на той системе, под которую собирает, — с Linux его не сделать.
rem
rem На выходе: dist\avito-watcher\ — папку можно целиком скопировать на другой
rem компьютер, Python там не нужен.
cd /d "%~dp0..\.."

if not exist ".venv" (
    echo Сначала запусти run.bat — он поставит окружение и браузер.
    pause
    exit /b 1
)

.venv\Scripts\python -m pip install --quiet pyinstaller || goto :fail

echo Собираю...
.venv\Scripts\python -m PyInstaller --noconfirm --clean ^
    --name avito-watcher ^
    --collect-all playwright ^
    --collect-all dotenv ^
    --hidden-import yaml ^
    deploy\windows\entry.py || goto :fail

rem Браузер кладём рядом с exe: бот сам его там найдёт (см. paths.py),
rem и папку можно переносить без установки Playwright на новой машине.
echo Копирую браузер рядом с exe...
set "PLAYWRIGHT_BROWSERS_PATH=%CD%\dist\avito-watcher\browsers"
.venv\Scripts\python -m playwright install chromium || goto :fail

copy config.yaml dist\avito-watcher\ >nul 2>nul
copy .env dist\avito-watcher\ >nul 2>nul

echo.
echo Готово: dist\avito-watcher\avito-watcher.exe
echo Рядом с exe должны лежать config.yaml и .env — если их не скопировало,
echo положи вручную.
pause
exit /b 0

:fail
echo.
echo Сборка не удалась. Последние строки выше объясняют, почему.
pause
exit /b 1
