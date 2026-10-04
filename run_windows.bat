@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -X faulthandler eggdesktop.py
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        python -X faulthandler eggdesktop.py
    ) else (
        echo Python 3 is not installed or is not in PATH.
        echo Install Python 3 and run this file again.
        pause
    )
)

if errorlevel 1 (
    echo.
    echo EggDesktop exited with an error.
    pause
)
