@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=python"
if exist "D:\software\Python\python.exe" set "PY=D:\software\Python\python.exe"

echo ========================================================
echo   Aigis Simplified Chinese Localization - APPLY PATCH
echo ========================================================
echo.
if not exist "patch_out\patch_manifest.json" (
    echo [Info] Building patch from local game directory...
    "%PY%" patcher.py build
    echo.
)
"%PY%" patcher.py apply
echo.
"%PY%" patcher.py status
echo.
pause
