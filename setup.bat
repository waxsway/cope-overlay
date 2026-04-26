@echo off
REM One-shot setup for friends. Installs Python deps, downloads sprites,
REM seeds the comp database. Run this ONCE after cloning/extracting the project.
REM
REM Prerequisites:
REM   - Python 3.11+ installed and on PATH (https://python.org)
REM   - (optional but recommended) Tesseract OCR installed
REM     (https://github.com/UB-Mannheim/tesseract/wiki — pick the latest 64-bit installer)

setlocal
cd /d "%~dp0"

echo.
echo === TFT Overlay Setup ===
echo.

REM 1. Verify Python
where py >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python launcher 'py' not found.
    echo Install Python 3.11+ from https://python.org with "Add to PATH" checked.
    pause
    exit /b 1
)

py --version
echo.

REM 2. Install Python dependencies
echo === Step 1/3: Installing Python packages (1-3 minutes)... ===
py -m pip install --upgrade pip >nul
py -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed. See output above.
    pause
    exit /b 1
)
echo.

REM 3. Download champion + item sprites
echo === Step 2/3: Downloading TFT sprites (~50MB, one-time)... ===
py scripts\download_sprites.py
if errorlevel 1 (
    echo WARNING: sprite download had issues. Recognition may not work.
    echo You can re-run: py scripts\download_sprites.py
)
echo.

REM 4. Seed comps + augments database
echo === Step 3/3: Loading meta comps + augments... ===
py scripts\seed_comps.py
echo.

echo === SETUP COMPLETE ===
echo.
echo Next steps:
echo   1. (Optional) Install Tesseract OCR for player-name auto-detection:
echo      https://github.com/UB-Mannheim/tesseract/wiki
echo   2. Double-click start.bat to launch the overlay.
echo   3. On first launch you'll be asked for your TFT in-game name.
echo.
pause
endlocal
