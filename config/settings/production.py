"""AWS ECS Fargate production settings."""
import warnings

from .base import *  # noqa: F401, F403

# Filter a noisy warning that Django emits every time WhiteNoise serves a
# static file under ASGI. WhiteNoise 6.x still uses wsgiref.util.FileWrapper
# (a synchronous iterator from the WSGI spec), which Django's ASGI handler
# wraps transparently via sync_to_async — correct behavior, but it logs a
# warning for each wrapped iteration. This floods the logs on every asset
# request.
#
# We scope the filter narrowly to WhiteNoise-served paths and keep it only
# in production settings so dev/test still surface the warning if it
# originates from application code. Remove this filter once WhiteNoise
# ships native async file iteration.
warnings.filterwarnings(
    "ignore",
    message="StreamingHttpResponse must consume synchronous iterators",
    module=r"django\.core\.handlers\.asgi",
)

DEBUG = False

# No default — fail loud on misconfiguration.
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")  # noqa: F405

# No default — fail loud on misconfiguration.
SECRET_KEY = env("DJANGO_SECRET_KEY")  # noqa: F405

# Standard DATABASE_URL — AWS RDS will provide it.
DATABASES = {"default": env.db("DATABASE_URL")}  # noqa: F405

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Channel layer is configured in base.py to use channels-redis pointing at
# REDIS_URL. connectlabs.py sources REDIS_URL from AWS Secrets Manager.
# See docs/learnings/channels-single-instance.md for the history.

# Security headers — production only
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
