@echo off
chcp 65001 >nul
title Колхоз — подключиться к серверу
setlocal

rem Клиент игры — это браузер. Файл спрашивает адрес сервера и открывает игру.
set FILE=%~dp0server.txt
if exist "%FILE%" (
  set /p ADDR=<"%FILE%"
  echo   Сохранённый адрес: %ADDR%
  set /p CHANGE=Открыть его? [Enter — да, или впишите другой]: 
  if not "%CHANGE%"=="" set ADDR=%CHANGE%
) else (
  echo   Адрес сервера вам даёт тот, кто его запустил.
  echo   Выглядит так: http://192.168.1.50:3000
  echo.
  set /p ADDR=Адрес сервера: 
)

if "%ADDR%"=="" (
  echo   Пустой адрес, выходим.
  pause
  exit /b 1
)

echo %ADDR%>"%FILE%"
start "" "%ADDR%"
