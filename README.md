Cheese Distribution Management System

A complete Django web application for managing a cheese distribution business.

Features:
- Manufacturer management
- Cheese inventory management
- Client management
- Sale creation and tracking
- Automatic profit calculation
- Stock management with automatic deduction
- Dashboard with business statistics

Setup Instructions:

1. Install Python 3.8 or higher

2. Create a virtual environment:
   python -m venv venv

3. Activate the virtual environment:
   On Windows:
   venv\Scripts\activate
   
   On Linux/Mac:
   source venv/bin/activate

4. Install dependencies:
   pip install -r requirements.txt

5. Run migrations:
   python manage.py makemigrations
   python manage.py migrate

6. Create a superuser account:
   python manage.py createsuperuser

7. Run the development server:
   python manage.py runserver

8. Access the application:
   Open your browser and go to http://127.0.0.1:8000/
   
   Login with the superuser credentials you created.

9. (Optional) Populate test data:
   python populate_test_data.py
   
   This creates sample manufacturers, cheese products, and clients for testing.
   You can delete this data later and replace it with your real data.

Database:
- Uses SQLite by default (db.sqlite3)
- Can easily switch to PostgreSQL using environment variables
- See database_config.md for detailed PostgreSQL setup instructions

To use PostgreSQL:
1. Install PostgreSQL and create a database
2. Set environment variables:
   Windows: set USE_SQLITE=False
   Windows: set DB_NAME=cheese_distribution
   Windows: set DB_USER=your_username
   Windows: set DB_PASSWORD=your_password
   Linux/Mac: export USE_SQLITE=False (and other DB_* variables)
3. Run migrations: python manage.py migrate

Project Structure:
- cheese_distribution/ - Main project directory
- distribution/ - Main application directory
  - models.py - Database models
  - views.py - View functions
  - forms.py - Form classes
  - urls.py - URL routing
  - templates/ - HTML templates
- static/ - Static files (CSS)
- manage.py - Django management script

