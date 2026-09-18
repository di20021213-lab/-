@echo off
chcp 65001 >nul
title Колхоз «Червонэ дышло» — сервер
cd /d "%~dp0.."

if not exist "kolhoz-server.exe" (
  if exist "dist\kolhoz-server.exe" (
    copy "dist\kolhoz-server.exe" "kolhoz-server.exe" >nul
  ) else (
    echo   Не нашёл kolhoz-server.exe рядом с проектом.
    echo   Положите файл сюда либо соберите его: node tools/build-exe.js win
    echo.
    pause
    exit /b 1
  )
)

if not exist ".env" (
  if exist ".env.example" copy ".env.example" ".env" >nul
)

echo   Запускаю сервер. Окно не закрывайте — пока оно открыто, игра работает.
echo   Адреса для игроков сервер напечатает сам.
echo.
kolhoz-server.exe

echo.
echo   Сервер остановлен.
pause
