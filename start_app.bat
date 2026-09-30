@echo off
setlocal
cd /d "%~dp0"

set PORT=%1
if "%PORT%"=="" set PORT=8000

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
)

echo Applying migrations...
python manage.py migrate --noinput
if errorlevel 1 (
    echo Migration failed. Is PostgreSQL running and .env correct?
    pause
    exit /b 1
)

start "" /b cmd /c "ping -n 5 127.0.0.1 >nul & start http://localhost:%PORT%/"

echo Starting server on http://localhost:%PORT%/  (press Ctrl+C to stop)
python manage.py runserver %PORT%
endlocal