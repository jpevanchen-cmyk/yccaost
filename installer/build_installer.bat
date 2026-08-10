@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 野草 · 编译 Inno 安装包

echo [1/2] 准备发布目录…
call "%~dp0prepare_dist.bat"
if errorlevel 1 exit /b 1

echo.
echo [2/2] 查找 Inno Setup 编译器…
set "ISCC="
if exist "E:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=E:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if "%ISCC%"=="" (
  echo.
  echo 未找到 Inno Setup 6 的 ISCC.exe。
  echo 请先安装：https://jrsoftware.org/isdl.php
  echo 或在管理员终端执行：
  echo   winget install --id JRSoftware.InnoSetup -e
  echo 装好后再双击本脚本。
  pause
  exit /b 1
)

echo 使用：%ISCC%
"%ISCC%" "%~dp0yecao_v1.iss"
if errorlevel 1 (
  echo 编译失败。若提示缺少 ChineseSimplified.isl，可把 iss 里中文语言那一行删掉再试。
  pause
  exit /b 1
)

echo.
echo 完成。安装包在：
echo   %~dp0output\
dir /b "%~dp0output\*.exe"
pause
