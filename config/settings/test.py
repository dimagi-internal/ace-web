"""Pytest settings.

Filters out apps and middleware that are forward-referenced in base.py
but not yet implemented during early Plan 1A tasks. As Tasks 4 and 5
add apps.auth and apps.sessions, the corresponding entries below should
be removed from the _unbuilt_* sets so the test environment matches base.
"""
from .base import *  # noqa: F401, F403

DEBUG = False
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
IAP_REQUIRED = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # fast hashing in tests

# --- Forward-reference filtering ---
# These entries exist in base.py because they're the eventual production shape,
# but the underlying code doesn't exist until later tasks. Tests run against a
# trimmed config until then.
_unbuilt_apps: set[str] = set()
_unbuilt_middleware: set[str] = set()

INSTALLED_APPS = [a for a in INSTALLED_APPS if a not in _unbuilt_apps]  # noqa: F405
MIDDLEWARE = [m for m in MIDDLEWARE if m not in _unbuilt_middleware]  # noqa: F405
