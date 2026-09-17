@echo off
chcp 65001 >nul
title Колхоз — ярлык для игрока
cd /d "%~dp0"

echo.
echo   Сделаем ярлык, который можно разослать игрокам.
echo   Адрес сервер печатает при запуске, например http://192.168.1.50:3000
echo.
set /p ADDR=Адрес сервера: 

if "%ADDR%"=="" (
  echo   Пустой адрес, ничего не делаю.
  pause
  exit /b 1
)

> "Kolhoz.url" echo [InternetShortcut]
>> "Kolhoz.url" echo URL=%ADDR%
>> "Kolhoz.url" echo IconIndex=0

echo.
echo   Готово: windows\Kolhoz.url — этот файл и рассылайте.
echo   Игроку достаточно открыть его в браузере. Ставить ничего не нужно.
echo.
pause
