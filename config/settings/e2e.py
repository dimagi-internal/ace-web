"""Playwright E2E test settings.

Inherits from development.py (DEBUG=True, ALLOWED_HOSTS=["*"],
ACE_ALLOW_TEST_LOGIN=True, ACE_USE_FAKE_CLI_BACKEND=True) but also
overrides the infrastructure dependencies so the test runner can start
the Django ASGI server (uvicorn) without Docker:

- Database: file-backed sqlite at BASE_DIR / "e2e-test.sqlite3"
  (created/migrated by the Playwright globalSetup hook; safe to delete
  between runs).
- Channel layer: InMemoryChannelLayer — cross-task fan-out is not
  exercised in a single-process uvicorn server, so channels-redis is
  unnecessary and would require a running Redis.
- FORCE_SCRIPT_NAME=/ace — matches the dev/prod path prefix so the
  hardcoded ``base: "/ace/"`` Vite build and ``basename: "/ace"`` React
  Router in ``frontend/`` can be served as-is without a separate build.
  Playwright drives the browser at ``/ace/...``. The whole app serves
  through a single uvicorn process (no nginx sidecar, no vite dev
  server), which is why we use uvicorn rather than ``manage.py
  runserver`` — runserver doesn't honour SCRIPT_NAME so the URL
  resolver double-prefixes the /ace segment.
- STATIC_URL points at ``frontend/dist/`` so WhiteNoise serves the
  built SPA assets (index.html, assets/*.js, assets/*.css) at
  ``/ace/assets/...``. The built index.html references ``/ace/assets/``
  directly, and WhiteNoise + FORCE_SCRIPT_NAME handle the prefix.

Do NOT use this settings module for multi-task tests or prod — it is
strictly for the local Playwright runner.
"""
from .development import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "e2e-test.sqlite3",  # noqa: F405
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

# Match docker-compose dev: serve the whole app under /ace/ so the
# Vite build's hardcoded base path lines up. uvicorn honours
# FORCE_SCRIPT_NAME correctly; runserver does not.
FORCE_SCRIPT_NAME = "/ace"

# Serve the built frontend as static files through WhiteNoise. The
# built index.html references /ace/assets/index-*.js — with
# FORCE_SCRIPT_NAME=/ace, WhiteNoise strips the /ace/ prefix and
# serves /assets/* via Django's staticfiles finders (enabled in
# DEBUG mode), which walks STATICFILES_DIRS.
#
# We point STATIC_URL at /assets/ (rather than the Django default
# /static/) so the lookup prefix matches the path the built SPA
# references. STATICFILES_DIRS contains the built dist directory so
# the finder discovers the index-*.js / index-*.css files.
STATIC_URL = "/assets/"
# STATIC_ROOT is unused at runtime (we don't run collectstatic for
# E2E) but still has to be set to *something* that doesn't
# collide with any STATICFILES_DIRS entry — Django's check E002
# blocks collisions. Point it at a throwaway path inside the repo
# that the tests never touch.
STATIC_ROOT = BASE_DIR / ".e2e-staticfiles-noop"  # noqa: F405
# STATICFILES_DIRS points at ``frontend/dist/assets/`` so
# ``finders.find("index-XXXX.js")`` resolves to
# ``frontend/dist/assets/index-XXXX.js``. WhiteNoise's DEBUG-mode
# lookup strips STATIC_URL from the URL and passes the remainder
# to Django's staticfiles finders — we want that remainder to
# match a file at the top level of the registered directory, not
# one nested under a further ``assets/`` subdirectory.
STATICFILES_DIRS = [str(BASE_DIR / "frontend" / "dist" / "assets")]  # noqa: F405
# The default CompressedManifestStaticFilesStorage expects a
# staticfiles.json manifest produced by `collectstatic`. The Vite
# build doesn't produce one, and we don't want to run collectstatic
# for E2E — fall back to the plain StaticFilesStorage which serves
# files as-is.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Point Django's template loader at the same dist directory so the
# SPA catch-all view (TemplateView index.html) renders the built
# index.html too.
TEMPLATES[0]["DIRS"] = [BASE_DIR / "frontend" / "dist"]  # noqa: F405

# Disable the real Connect OAuth config check so dev-only fixtures
# don't need to supply credentials. The test-login view is the only
# auth path Playwright exercises.
CONNECT_OAUTH_CLIENT_ID = "e2e-noop"
CONNECT_OAUTH_CLIENT_SECRET = "e2e-noop"
