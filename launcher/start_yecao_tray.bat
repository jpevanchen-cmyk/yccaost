@echo off
cd /d "%~dp0"
if not exist "%~dp0start_yecao_tray.vbs" (
    echo Missing start_yecao_tray.vbs
    pause
    exit /b 1
)
wscript.exe //B //Nologo "%~dp0start_yecao_tray.vbs"
