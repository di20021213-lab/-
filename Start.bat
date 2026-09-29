@echo off
rem Silent Installer - opens the program window.
setlocal
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
start "" "%PS%" -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0SilentInstaller.ps1"
