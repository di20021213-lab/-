@echo off
rem Silent Installer - installs ALL programs found in the Distrib folder, without the window.
rem Already installed programs are skipped. Remove -SkipInstalled to reinstall them.
setlocal
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0SilentInstaller.ps1" -All -SkipInstalled
pause
