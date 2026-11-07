@echo off
title TVBox Deploy to GitHub
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERROR] Python not found on this computer.
  echo Please tell the assistant: python missing.
  echo.
  pause
  exit /b 1
)

python deploy_to_github.py

echo.
echo ---------------------------------------------
echo Done. You can close this window now.
pause
