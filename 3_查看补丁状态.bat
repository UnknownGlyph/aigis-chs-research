@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=python"
if exist "D:\software\Python\python.exe" set "PY=D:\software\Python\python.exe"

echo ========================================================
echo   Aigis Simplified Chinese Localization - CHECK STATUS
echo ========================================================
echo.
"%PY%" patcher.py status
echo.
pause
