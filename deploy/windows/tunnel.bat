@echo off
chcp 65001 >nul
rem Туннель для Telegram — замена autossh с Linux.
rem
rem Зачем: api.telegram.org из России не открывается напрямую, поэтому бот
rem ходит туда через SOCKS-прокси на зарубежном сервере. В .env это строка
rem TELEGRAM_PROXY=socks5h://127.0.0.1:1080 — она остаётся прежней, меняется
rem только то, кто держит туннель.
rem
rem ssh.exe в Windows уже есть (начиная с Windows 10), ставить нечего.
rem Ключ должен лежать в %USERPROFILE%\.ssh\id_ed25519 — скопируй его с мини-ПК.
rem
rem Окно не закрывать. Для постоянной работы — через Планировщик задач,
rem как описано в README.md рядом.

set VDS_USER=root
set VDS_HOST=87.58.205.159
set VDS_PORT=22

:loop
echo %date% %time%  подключаюсь к %VDS_HOST%...
ssh -N -D 127.0.0.1:1080 ^
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 ^
    -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new ^
    -p %VDS_PORT% %VDS_USER%@%VDS_HOST%

rem Сюда попадаем, только если соединение оборвалось: ждём и поднимаем заново.
echo %date% %time%  связь оборвалась, повтор через 15 секунд
timeout /t 15 /nobreak >nul
goto loop
