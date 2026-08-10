@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 野草 · 本机忘记密码重置
echo 正在打开本机忘记密码重置窗口...
if exist ".venv\Scripts\pythonw.exe" (
  ".venv\Scripts\pythonw.exe" -m launcher.yecao_password_reset_ui
) else if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m launcher.yecao_password_reset_ui
) else (
  python -m launcher.yecao_password_reset_ui
)
if errorlevel 1 (
  echo.
  echo 启动失败。也可在项目目录执行：
  echo   .\.venv\Scripts\python.exe manage.py yecao_reset_local_password
  pause
)
