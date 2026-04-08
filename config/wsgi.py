"""WSGI fallback. Production uses ASGI via uvicorn; this exists for tooling compatibility."""
import os

from django.core.wsgi import get_wsgi_application

# Defaults to production because uvicorn/daphne are the production entry points.
# Local dev overrides this via DJANGO_SETTINGS_MODULE in docker-compose or shell.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

application = get_wsgi_application()
