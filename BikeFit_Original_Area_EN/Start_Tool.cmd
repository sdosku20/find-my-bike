@echo off
setlocal
cd /d "%~dp0"
title BikeFit - Live Video Gap Areas
"%~dp0runtime\python.exe" "%~dp0tool\launch.py"
if errorlevel 1 (
  echo.
  echo Please keep all extracted files together and try again.
  pause
  exit /b 1
)
echo Press any key to close this message. The local tool will stay available.
pause >nul
