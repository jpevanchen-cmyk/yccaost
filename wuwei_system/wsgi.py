"""
WSGI config for wuwei_system project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

# 生产 gunicorn 入口：先保证 SQLite 版本满足 Django 5.2
from wuwei_system.sqlite_compat import ensure_sqlite_compatible

ensure_sqlite_compatible()

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wuwei_system.settings')

application = get_wsgi_application()
