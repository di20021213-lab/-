@echo off
chcp 65001 >nul
title Колхоз — открыть порт в брандмауэре
rem Порт должен совпадать с PORT из .env
set PORT=3000

net session >nul 2>nul
if errorlevel 1 (
  echo   Нужны права администратора.
  echo   Закройте это окно, нажмите на файле правой кнопкой — "Запуск от имени администратора".
  echo.
  pause
  exit /b 1
)

netsh advfirewall firewall delete rule name="Kolhoz Chervone Dyshlo" >nul 2>nul
netsh advfirewall firewall add rule name="Kolhoz Chervone Dyshlo" dir=in action=allow protocol=TCP localport=%PORT%
if errorlevel 1 (
  echo   Правило не добавилось.
  pause
  exit /b 1
)

echo.
echo   Порт %PORT% открыт для входящих. Теперь игроки из вашей сети достучатся до сервера.
echo   Убрать правило обратно:
echo       netsh advfirewall firewall delete rule name="Kolhoz Chervone Dyshlo"
echo.
pause
