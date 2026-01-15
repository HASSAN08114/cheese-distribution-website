Git Setup Instructions

How to Share This Project with Your Friend

OPTION 1: Using GitHub (Recommended)

Step 1: Create a GitHub Repository
1. Go to https://github.com and sign in
2. Click the "+" icon in the top right, select "New repository"
3. Name it: cheese-distribution-website
4. Choose Public or Private
5. DO NOT initialize with README, .gitignore, or license (we already have these)
6. Click "Create repository"

Step 2: Initialize Git and Push (On Your Computer)

Open terminal/command prompt in the project folder and run:

git init
git add .
git commit -m "Initial commit: Cheese Distribution Django application"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/cheese-distribution-website.git
git push -u origin main

Replace YOUR_USERNAME with your actual GitHub username.

Step 3: Share with Your Friend

Send them the repository URL:
https://github.com/YOUR_USERNAME/cheese-distribution-website

Your friend can then clone it using:
git clone https://github.com/YOUR_USERNAME/cheese-distribution-website.git
cd cheese-distribution-website

OPTION 2: Using GitLab

Similar process:
1. Go to https://gitlab.com and create a repository
2. Follow the same git commands but use GitLab repository URL

OPTION 3: Using Bitbucket

Similar process:
1. Go to https://bitbucket.org and create a repository
2. Follow the same git commands but use Bitbucket repository URL

OPTION 4: Share via ZIP (No Git)

If you don't want to use Git:
1. Create a ZIP file of the project folder
2. Exclude: __pycache__, db.sqlite3, .git folder
3. Share the ZIP file
4. Your friend will need to:
   - Extract the ZIP
   - Create a virtual environment
   - Install requirements: pip install -r requirements.txt
   - Run migrations: python manage.py migrate
   - Create superuser: python manage.py createsuperuser

IMPORTANT NOTES:

1. The .gitignore file will exclude:
   - Database file (db.sqlite3)
   - Python cache files (__pycache__)
   - Virtual environment folders
   - Environment variables (.env)
   - Log files

2. Your friend needs to:
   - Create their own database (run migrations)
   - Create their own superuser account
   - Set up their own virtual environment
   - Install dependencies from requirements.txt

3. Sensitive Data:
   - The SECRET_KEY in settings.py is for development only
   - Change it in production: python manage.py generate_secret_key
   - Never commit real production database

4. After Your Friend Clones:
   cd cheese-distribution-website
   python -m venv venv
   venv\Scripts\activate  (Windows)
   source venv/bin/activate  (Linux/Mac)
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py runserver

Quick Git Commands Reference:

git status - Check what files are changed
git add . - Add all files to staging
git commit -m "message" - Commit changes with a message
git push - Push changes to remote repository
git pull - Pull latest changes from remote repository
git log - View commit history

