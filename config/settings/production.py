"""Cloud Run production settings."""
import os

from .base import *  # noqa: F401, F403

DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[".run.app"])  # noqa: F405
IAP_REQUIRED = True

# Cloud SQL via Unix socket when CLOUD_SQL_CONNECTION_NAME is set
CLOUD_SQL = os.environ.get("CLOUD_SQL_CONNECTION_NAME")
if CLOUD_SQL:
    DATABASES["default"]["HOST"] = f"/cloudsql/{CLOUD_SQL}"  # noqa: F405

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
