@echo off
chcp 65001 >nul
rem Запуск бота на Windows без сборки exe. Двойной щелчок по этому файлу.
rem При первом запуске поставит зависимости и браузер — это займёт минут пять.
cd /d "%~dp0..\.."

where python >nul 2>nul
if errorlevel 1 (
    echo Не найден Python. Поставь его с python.org и при установке
    echo обязательно отметь галочку "Add python.exe to PATH".
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Создаю окружение...
    python -m venv .venv || goto :fail
)

echo Проверяю зависимости...
.venv\Scripts\python -m pip install --quiet --upgrade pip || goto :fail
.venv\Scripts\python -m pip install --quiet -r requirements.txt || goto :fail

rem Ставится один раз; при повторных запусках просто убеждается, что браузер на месте.
.venv\Scripts\python -m playwright install chromium || goto :fail

if not exist "config.yaml" (
    echo.
    echo Нет config.yaml. Скопируй config.multiregion.example.yaml в config.yaml
    echo и впиши свои поиски, а в .env — токен бота и chat_id.
    pause
    exit /b 1
)

echo.
echo Запускаю. Окно не закрывай — бот работает, пока оно открыто.
echo Остановить: Ctrl+C
echo.
.venv\Scripts\python -m avito_watcher.main %*
pause
exit /b 0

:fail
echo.
echo Не получилось. Скопируй последние строки выше — по ним видно, что именно.
pause
exit /b 1
