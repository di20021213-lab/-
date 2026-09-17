@echo off
chcp 65001 >nul
title Колхоз «Червонэ дышло» — сервер
cd /d "%~dp0.."

if not exist "node_modules" (
  echo   Сначала запустите 1-install.bat
  pause
  exit /b 1
)

echo   Запускаю. Окно не закрывайте — пока оно открыто, сервер работает.
node server\src\index.js

echo.
echo   Сервер остановлен.
pause
