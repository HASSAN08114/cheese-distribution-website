import os

from django.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cheese_distribution.settings')

application = get_asgi_application()

