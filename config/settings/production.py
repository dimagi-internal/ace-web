"""Cloud Run production settings."""
import os
import warnings

from .base import *  # noqa: F401, F403

# Filter a noisy warning that Django emits every time WhiteNoise serves a
# static file under ASGI. WhiteNoise 6.x still uses wsgiref.util.FileWrapper
# (a synchronous iterator from the WSGI spec), which Django's ASGI handler
# wraps transparently via sync_to_async — correct behavior, but it logs a
# warning for each wrapped iteration. This floods the Cloud Run logs on
# every asset request.
#
# We scope the filter narrowly to WhiteNoise-served paths and keep it only
# in production settings so dev/test still surface the warning if it
# originates from application code. Remove this filter once WhiteNoise
# ships native async file iteration (upstream issue: whitenoise project
# still tracking WSGI-first design).
warnings.filterwarnings(
    "ignore",
    message="StreamingHttpResponse must consume synchronous iterators",
    module=r"django\.core\.handlers\.asgi",
)

DEBUG = False
# No default — cloudbuild.yaml must pass the actual Cloud Run hostname.
# Missing value causes a startup error, which is what we want in production.
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")  # noqa: F405
IAP_REQUIRED = True

# Production must have these set in the environment — no fallback to the
# insecure dev default in base.py. Missing env vars cause immediate startup crash.
SECRET_KEY = env("DJANGO_SECRET_KEY")  # noqa: F405

# Cloud SQL via Unix socket when CLOUD_SQL_CONNECTION_NAME is set
CLOUD_SQL = os.environ.get("CLOUD_SQL_CONNECTION_NAME")
if CLOUD_SQL:
    DATABASES["default"]["HOST"] = f"/cloudsql/{CLOUD_SQL}"  # noqa: F405

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# WARNING: CHANNEL_LAYERS in base.py uses InMemoryChannelLayer which only
# works in single-process mode. Plan 1C must replace this with channels-redis
# before scaling Cloud Run beyond min/max=1 instance.

# Security headers — production only
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
