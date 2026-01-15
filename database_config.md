Database Configuration Guide

The application supports both SQLite (default) and PostgreSQL databases.

SQLite (Default - Development):
- Already configured and ready to use
- No additional setup required
- Database file: db.sqlite3

PostgreSQL (Production):

1. Install PostgreSQL on your system

2. Create a database:
   CREATE DATABASE cheese_distribution;

3. Install PostgreSQL adapter:
   pip install psycopg2-binary

4. Set environment variables to switch to PostgreSQL:
   
   Windows (PowerShell):
   $env:USE_SQLITE="False"
   $env:DB_NAME="cheese_distribution"
   $env:DB_USER="your_username"
   $env:DB_PASSWORD="your_password"
   $env:DB_HOST="localhost"
   $env:DB_PORT="5432"
   
   Windows (Command Prompt):
   set USE_SQLITE=False
   set DB_NAME=cheese_distribution
   set DB_USER=your_username
   set DB_PASSWORD=your_password
   set DB_HOST=localhost
   set DB_PORT=5432
   
   Linux/Mac:
   export USE_SQLITE=False
   export DB_NAME=cheese_distribution
   export DB_USER=your_username
   export DB_PASSWORD=your_password
   export DB_HOST=localhost
   export DB_PORT=5432

5. Run migrations:
   python manage.py makemigrations
   python manage.py migrate

6. Create superuser:
   python manage.py createsuperuser

Alternative: Create .env file (requires python-decouple):
   USE_SQLITE=False
   DB_NAME=cheese_distribution
   DB_USER=your_username
   DB_PASSWORD=your_password
   DB_HOST=localhost
   DB_PORT=5432

To switch back to SQLite, set:
   USE_SQLITE=True
   (or remove the environment variable)

