CSRF Token Error Troubleshooting

If you encounter "CSRF verification failed" errors, try these solutions:

1. Clear Browser Cache and Cookies:
   - Clear your browser cache
   - Delete cookies for localhost:8000
   - Restart your browser

2. Hard Refresh the Page:
   - Windows/Linux: Ctrl + F5 or Ctrl + Shift + R
   - Mac: Cmd + Shift + R

3. Check Browser Settings:
   - Ensure cookies are enabled
   - Disable browser extensions that might block cookies
   - Try in incognito/private mode

4. Restart Django Server:
   - Stop the server (Ctrl + C)
   - Clear Django session data if needed
   - Restart: python manage.py runserver

5. Verify CSRF Token in Form:
   - Right-click on the form and "Inspect Element"
   - Look for: <input type="hidden" name="csrfmiddlewaretoken" value="...">
   - If missing, the template might not be rendering correctly

6. Check Settings:
   - Ensure 'django.middleware.csrf.CsrfViewMiddleware' is in MIDDLEWARE
   - Verify DEBUG = True for development

7. If Using Multiple Tabs:
   - Close all tabs with the application
   - Open a fresh tab and navigate to the site
   - CSRF tokens rotate after login

8. Database/Session Issues:
   - If using SQLite, ensure db.sqlite3 is not locked
   - Try deleting session data: python manage.py clearsessions

Common Causes:
- Submitting a form after session expired
- Using browser back button after login
- Multiple browser tabs with different sessions
- Browser extensions blocking cookies
- Cached form with old CSRF token

