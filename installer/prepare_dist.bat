@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 野草 · 准备安装包发布目录
echo ========================================
echo  准备发布目录（含内嵌运行环境）
echo  源项目：上级目录
echo  目标：installer\staging\app
echo ========================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_dist.ps1"
if errorlevel 1 (
  echo.
  echo 准备失败。
  pause
  exit /b 1
)
echo.
echo 完成。下一步可用 Inno Setup 编译 yecao_v1.iss
echo 或双击 build_installer.bat（须已安装 Inno Setup 6）
pause
