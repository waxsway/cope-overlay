@echo off
REM Double-click this to launch the TFT overlay.
REM Stays open on errors so you can read the message before closing.

cd /d "%~dp0"
py -m src.main
echo.
echo ========================================
echo Overlay closed. Press any key to exit.
echo ========================================
pause >nul
