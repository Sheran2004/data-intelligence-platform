@echo off
REM AI Data Intelligence Platform - quick start for Windows

REM Create virtual environment if it doesn't exist
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate

REM Install deps
echo Installing dependencies...
pip install -q -r requirements.txt

REM Start the app
echo.
echo ================================================
echo   Data Intelligence Platform is starting...
echo   Open http://localhost:5000 in your browser.
echo ================================================
echo.
python app.py