# Cheese Distribution Application - Setup Instructions

## For First Time Setup

1. **Open Command Prompt (CMD)** in this folder
2. **Run the setup script:**
   ```
   setup.bat
   ```
   This will:
   - Create a Python virtual environment
   - Install all required packages
   - Set up the database
   - Ask you to create a superuser account (admin username and password)

3. **Wait for setup to complete** - it may take a few minutes

## To Run the Application

1. **Open Command Prompt (CMD)** in this folder
2. **Run the application:**
   ```
   run.bat
   ```
   This will:
   - Start the Django server
   - Automatically open your browser to http://127.0.0.1:8000/
   - Display login screen

3. **Login** with the username and password you created during setup

4. **Press Ctrl+C** in the command prompt to stop the server

## Features

- **Client Management** - Add, edit, delete clients
- **Inventory Management** - Track cheese products and stock
- **Sales Management** - Create and track sales
- **Payment Management** - Record client payments
- **PDF Reports** - Export client reports with sales and payment history by date range
- **Dashboard** - View analytics and metrics

## Files Included

- `setup.bat` - Run this first to initialize the project
- `run.bat` - Run this to start the application
- `manage.py` - Django management script
- `requirements.txt` - All Python dependencies (automatically installed)

## Troubleshooting

**If you see "Python not found":**
- Make sure Python 3.8+ is installed on your computer
- Add Python to your system PATH

**If setup fails:**
- Try running Command Prompt as Administrator
- Delete the `.venv` folder and run setup.bat again

**If the server won't start:**
- Make sure port 8000 is not already in use
- Close other applications using the same port

## Contact

For support or issues, contact the developer.
