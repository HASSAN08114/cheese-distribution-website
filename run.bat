@echo off
REM Run script - Execute this to start the application
echo ====================================
echo Cheese Distribution - Starting Server
echo ====================================
echo.

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Start Django server and open browser
echo Starting Django server...
echo Opening browser at http://127.0.0.1:8000/
echo.
echo Press Ctrl+C to stop the server.
echo.

start http://127.0.0.1:8000/
python manage.py runserver
