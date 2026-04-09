"""Pytest settings: in-memory SQLite + fast hashers + in-memory channel layer."""
from .base import *  # noqa: F401, F403

DEBUG = False
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Strip WhiteNoise from the middleware chain in tests. WhiteNoise's
# middleware __init__ warns if STATIC_ROOT doesn't exist, and tests don't
# run collectstatic so the directory is empty/absent — every middleware-
# using test then emits `No directory at: .../staticfiles/`. The Django
# test client doesn't need WhiteNoise to serve static files anyway.
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m.lower()]  # noqa: F405
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Channels: use the in-memory layer for tests. WebsocketCommunicator tests
# run inside a single process so cross-task fan-out is not exercised here
# (those guarantees are covered by channels_redis's own test suite). Our
# tests just need deterministic, synchronous group_send behavior.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

# Tests that exercise presence.py patch apps.common.redis_client.get_redis
# with a fakeredis instance. ACE_REDIS_URL is unused in that path but kept
# valid so redis_client.get_redis() without the patch still constructs.
ACE_REDIS_URL = "redis://localhost:6379/15"

# Unit tests must NOT hit the dev-only test hooks; they patch directly
# at the function level. Explicit False here overrides any accidental
# inheritance if development.py ever becomes a parent.
ACE_ALLOW_TEST_LOGIN = False
ACE_USE_FAKE_CLI_BACKEND = False
