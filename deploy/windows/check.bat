@echo off
chcp 65001 >nul
rem Разовая проверка настройки: что бот видит и как отработали фильтры.
rem Ничего не отправляет и не пишет в базу.
cd /d "%~dp0..\.."
if not exist ".venv" (
    echo Сначала запусти run.bat — он поставит окружение.
    pause
    exit /b 1
)
.venv\Scripts\python -m avito_watcher.main --check
pause
