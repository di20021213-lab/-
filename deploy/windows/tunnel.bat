@echo off
rem SSH tunnel to the foreign VDS: SOCKS5 for Telegram + remote desktop forward.
rem Replaces autossh from the Linux setup. See RDP.md for the Russian guide.
rem
rem NOTE: this file is deliberately ASCII-only. cmd.exe reads batch files in the
rem OEM codepage, so UTF-8 Cyrillic here breaks line parsing and random fragments
rem get executed as commands. Keep explanations in the .md files.
rem
rem Key must be at %USERPROFILE%\.ssh\id_ed25519 (see AFTER_INSTALL.md).

set VDS_USER=root
set VDS_HOST=87.58.205.159
set VDS_PORT=22

:loop
echo [%date% %time%] connecting to %VDS_HOST% ...
ssh -N ^
    -D 127.0.0.1:1080 ^
    -R 127.0.0.1:3389:127.0.0.1:3389 ^
    -o ServerAliveInterval=30 ^
    -o ServerAliveCountMax=3 ^
    -o ExitOnForwardFailure=yes ^
    -o StrictHostKeyChecking=accept-new ^
    -p %VDS_PORT% %VDS_USER%@%VDS_HOST%

rem We only get here if the connection dropped. Wait and bring it back up.
echo [%date% %time%] tunnel down, retry in 15 s
timeout /t 15 /nobreak >nul
goto loop
