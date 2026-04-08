"""WSGI fallback. Production uses ASGI via uvicorn; this exists for tooling compatibility."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

application = get_wsgi_application()
