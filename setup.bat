@echo off
REM Setup script - Run this first to initialize the project
echo ====================================
echo Cheese Distribution - Initial Setup
echo ====================================
echo.

REM Create virtual environment if it doesn't exist
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    echo Virtual environment created.
) else (
    echo Virtual environment already exists.
)

REM Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate.bat

REM Install requirements
echo Installing dependencies...
pip install -r requirements.txt

REM Run migrations
echo Running database migrations...
python manage.py migrate

REM Create superuser
echo.
echo ====================================
echo Create Superuser Account
echo ====================================
echo Enter your superuser credentials:
python manage.py createsuperuser

echo.
echo ====================================
echo Setup Complete!
echo ====================================
echo You can now run the application using: run.bat
echo.
pause
