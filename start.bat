@echo off
rem Launch the local AI assistant (double-click this file).
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 agent.py %*
) else (
    python agent.py %*
)
pause
