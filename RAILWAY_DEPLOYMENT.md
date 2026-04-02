# Railway Deployment Guide

## Overview
This guide will help you deploy your Cheese Distribution Django application to Railway.

## Prerequisites
1. Create a [Railway account](https://railway.app)
2. Install [Railway CLI](https://docs.railway.app/guides/cli)
3. Have Git installed and your project committed

## Step-by-Step Deployment

### 1. Set Up Environment Variables on Railway
In your Railway project dashboard, add these variables:

```
DEBUG=False
SECRET_KEY=<your-secure-random-string>
ALLOWED_HOSTS=your-domain.railway.app,www.your-domain.railway.app
```

Generate a secure SECRET_KEY using Python:
```python
from django.core.management.utils import get_random_secret_key
print(get_random_secret_key())
```

### 2. Connect PostgreSQL Database
1. In Railway Dashboard, click "New"
2. Select "PostgreSQL"
3. Railway automatically creates the `DATABASE_URL` environment variable
4. This will be automatically detected by `dj_database_url`

### 3. Create a `.env` file for Local Development
Copy from `.env.example`:
```
# For local SQLite development
DATABASE_URL=sqlite:///db.sqlite3
DEBUG=True
SECRET_KEY=your-local-dev-key
ALLOWED_HOSTS=localhost,127.0.0.1
```

### 4. Deploy to Railway

#### Option A: Using Railway CLI
```bash
# Login to Railway
railway login

# Initialize Railway project
railway init

# Deploy
railway up
```

#### Option B: Using GitHub Integration
1. Push your code to GitHub
2. In Railway Dashboard, click "New Project"
3. Select "GitHub Repo"
4. Follow the prompts

### 5. Run Migrations & Create Superuser
After deployment:

```bash
# Run migrations
railway run python manage.py migrate

# Create superuser
railway run python manage.py createsuperuser
```

### 6. Collect Static Files
Railway automatically runs `python manage.py collectstatic` during deployment via the Procfile.

## Important Files
- `Procfile` - Defines how Railway runs your application
- `runtime.txt` - Specifies Python version
- `.env.example` - Template for environment variables
- `requirements.txt` - Python dependencies (includes gunicorn, dj-database-url)

## Database Configuration
Your app now uses `dj_database_url.config()` which:
- Automatically reads `DATABASE_URL` from environment variables
- Falls back to SQLite for local development
- Automatically configures all database parameters

## Security Settings
The settings.py now includes:
- `SECURE_SSL_REDIRECT` - Redirects HTTP to HTTPS in production
- `SESSION_COOKIE_SECURE` - Only sends session cookie over HTTPS
- `CSRF_COOKIE_SECURE` - Only sends CSRF cookie over HTTPS
- `SECURE_HSTS_HEADERS` - Enforce HTTPS for future requests

## Troubleshooting

### 502 Bad Gateway Error
- Check logs: `railway logs`
- Ensure DATABASE_URL is set correctly
- Verify all environment variables are configured

### Static Files Not Loading
- Run: `railway run python manage.py collectstatic --noinput`
- Ensure `STATIC_URL` and `STATIC_ROOT` are configured

### Database Connection Issues
- Verify PostgreSQL service is running in Railway
- Check DATABASE_URL format is correct
- Ensure firewall/network access is allowed

### Debug Mode
For troubleshooting, you can temporarily set `DEBUG=True`, but it's not recommended for long-term production use.

## Additional Resources
- [Railway Documentation](https://docs.railway.app)
- [Django Deployment Checklist](https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/)
- [dj-database-url Documentation](https://github.com/jazzband/dj-database-url)
