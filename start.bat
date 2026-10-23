@echo off
echo ========================================
echo   Jingyu - Bilibili Assistant
echo ========================================
echo.

cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [Error] Python not found
    pause
    exit /b 1
)

echo [1/2] Creating directories...
if not exist "data\logs" mkdir "data\logs"

echo [2/2] Starting program (missing dependencies are installed automatically)...
echo.
python main.py

if errorlevel 1 (
    echo.
    echo [Error] Program crashed
    pause
)
