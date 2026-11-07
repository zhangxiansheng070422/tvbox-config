@echo off
chcp 65001 >nul
title 点播源 - 粘贴就生效
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo   [错误] 这台电脑找不到 Python。
  echo   跟助手说一句 "python missing" 就行。
  echo.
  pause
  exit /b 1
)

echo.
echo   浏览器马上自动打开。没打开的话，手动访问下面显示的地址。
echo   提交完就可以直接关掉这个窗口。
echo.

python sources_editor.py

echo.
echo   编辑器已退出。
pause
