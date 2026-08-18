@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 野草 · 本机忘记密码重置
echo 正在打开本机忘记密码重置窗口...
if exist ".venv\pythonw.exe" (
  ".venv\pythonw.exe" -m launcher.yecao_password_reset_ui
) else if exist ".venv\Scripts\pythonw.exe" (
  ".venv\Scripts\pythonw.exe" -m launcher.yecao_password_reset_ui
) else if exist ".venv\python.exe" (
  ".venv\python.exe" -m launcher.yecao_password_reset_ui
) else if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m launcher.yecao_password_reset_ui
) else (
  echo 找不到运行环境。安装包请重新安装；开发机请确认已创建 .venv。
  pause
  exit /b 1
)
if errorlevel 1 (
  echo.
  echo 启动失败。
  pause
)
