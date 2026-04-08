"""Pytest settings: in-memory SQLite + fast hashers."""
import os

from .base import *  # noqa: F401, F403

# Allow synchronous ORM calls from async test functions (pytest-asyncio tests
# use sync ORM helpers like session.save() / session.refresh_from_db() in the
# test body; the async safety guard would otherwise reject those calls).
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

DEBUG = False
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
IAP_REQUIRED = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Strip WhiteNoise from the middleware chain in tests. WhiteNoise's
# middleware __init__ warns if STATIC_ROOT doesn't exist, and tests don't
# run collectstatic so the directory is empty/absent — every middleware-
# using test then emits `No directory at: .../staticfiles/`. The Django
# test client doesn't need WhiteNoise to serve static files anyway.
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m.lower()]  # noqa: F405
# Also drop the manifest storage since there's no manifest in tests.
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
