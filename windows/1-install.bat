@echo off
chcp 65001 >nul
title Колхоз «Червонэ дышло» — установка
cd /d "%~dp0.."

echo.
echo   Установка колхоза. Это делается один раз.
echo.

where node >nul 2>nul
if errorlevel 1 (
  echo   Node.js не найден.
  echo   Поставьте LTS-версию с https://nodejs.org — кнопка LTS, установка обычная.
  echo   Потом перезапустите этот файл.
  echo.
  pause
  exit /b 1
)

for /f "delims=" %%v in ('node -v') do echo   Node.js: %%v
echo.

echo   Ставлю зависимости...
call npm install
if errorlevel 1 (
  echo.
  echo   Не установилось. Частая причина: у better-sqlite3 нет готовой сборки
  echo   под вашу версию Node. Поставьте Node.js LTS 64-бит — с ним сборка готовая.
  echo.
  pause
  exit /b 1
)

echo.
echo   Создаю базу...
call npm run migrate
if errorlevel 1 (
  echo   База не создалась.
  pause
  exit /b 1
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo   Создан файл .env — настройки лежат там.
)

echo.
echo   Готово. Дальше запускайте 2-start-server.bat
echo.
pause
