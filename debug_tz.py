import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cheese_distribution.settings')
django.setup()

from django.utils import timezone
from datetime import datetime
from django.conf import settings

print(f"Django TIME_ZONE setting: {settings.TIME_ZONE}")
print(f"Django USE_TZ setting: {settings.USE_TZ}")
print(f"Current datetime.now(): {datetime.now()}")
print(f"Current timezone.now(): {timezone.now()}")
print(f"Current timezone.now().date(): {timezone.now().date()}")
print(f"Current timezone.localtime().date(): {timezone.localtime(timezone.now()).date()}")
print(f"UTC now: {timezone.now()}")

