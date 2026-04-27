"""Shared Django settings for ace-web."""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env()
# Only read .env file if it exists. Production reads from process env only
# (Cloud Run + Secret Manager) — there is no .env file in the container.
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env")

# --- Core ---
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-key-change-me")
# Field-level encryption key for UserCredential.blob_encrypted (and any
# future EncryptedTextField columns). Prod REQUIRES a dedicated key via
# ACE_FIELD_ENCRYPTION_KEY; dev/CI falls back to SECRET_KEY for ergonomics.
_explicit_field_key = env("ACE_FIELD_ENCRYPTION_KEY", default="")
if _explicit_field_key:
    FIELD_ENCRYPTION_KEY = _explicit_field_key.encode("utf-8")
else:
    FIELD_ENCRYPTION_KEY = SECRET_KEY.encode("utf-8")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
# base.py default is empty so a misconfigured production deploy fails loudly
# instead of silently disabling Host header validation. development.py overrides
# this to ["*"] for local convenience.
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# URL path prefix — set to "/ace" in the labs deployment (and the prod-parity
# local docker-compose profile) so Django serves under /ace/*. None by default
# so a bare `./manage.py runserver` serves at root. Empty string is coerced to
# None because Django treats "" as a truthy path and generates URLs like
# "//api/health" (double slash).
FORCE_SCRIPT_NAME = env("FORCE_SCRIPT_NAME", default="") or None

# --- Apps ---
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "channels",
    # Local apps
    "apps.common",
    "apps.auth.apps.AuthConfig",
    "apps.sessions.apps.SessionsConfig",
    "apps.opps.apps.OppsConfig",
    "apps.ingest.apps.IngestConfig",
    "apps.service_accounts.apps.ServiceAccountsConfig",
    "apps.system.apps.SystemConfig",
    "apps.workspaces.apps.WorkspacesConfig",
]

AUTH_USER_MODEL = "ace_auth.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "frontend" / "dist"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database ---
DATABASES = {
    "default": env.db("DATABASE_URL", default="sqlite:///db.sqlite3"),
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Channels ---
# channels-redis is the cross-process channel layer for WebSocket broadcasts.
# Local dev and AWS prod both point at a real Redis; tests override this
# back to InMemoryChannelLayer in config/settings/test.py for speed and
# isolation. See docs/learnings/channels-single-instance.md.
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
ACE_REDIS_URL = REDIS_URL
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
        },
    },
}

# --- Static files (WhiteNoise) ---
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = []
_frontend_dist = BASE_DIR / "frontend" / "dist"
if _frontend_dist.exists():
    STATICFILES_DIRS.append(_frontend_dist)
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# --- I18N ---
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- CommCare Connect OAuth (labs / AWS deployment) ---
CONNECT_PRODUCTION_URL = env("CONNECT_PRODUCTION_URL", default="https://connect.dimagi.com")
CONNECT_OAUTH_CLIENT_ID = env("CONNECT_OAUTH_CLIENT_ID", default="")
CONNECT_OAUTH_CLIENT_SECRET = env("CONNECT_OAUTH_CLIENT_SECRET", default="")
CONNECT_OAUTH_SCOPES = ["read", "openid"]

# Django auth wiring
LOGIN_URL = "/auth/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/auth/login/"

# --- Claude integration ---
# CLI backend (Phase 2): spawns `claude -p` as a subprocess. The OAuth token
# is persisted in the ace_common_systemconfig DB table (see auth_flow.py) —
# no on-disk token file, no Secrets Manager entry.
ACE_CLAUDE_HOME = env(
    "ACE_CLAUDE_HOME",
    default=str(BASE_DIR / ".ace-claude-home"),
)
# API backend (fallback): direct Anthropic API access when CLI is not connected.
# Set via ANTHROPIC_API_KEY env var or AWS Secrets Manager.
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")

# Top-level Drive folder that holds ACE opportunities. Default matches the
# ACE plugin convention.
ACE_DRIVE_ROOT_FOLDER_NAME = env("ACE_DRIVE_ROOT_FOLDER_NAME", default="ACE")
# Pinned folder id for the ACE root. When set, apps.opps.views resolves the
# root folder directly from this id instead of doing a name-based lookup.
# This is the primary mechanism in production; the name-based fallback is
# reserved for future hypothetical multi-tenant scenarios. Sourced from the
# shared "ACE" Google Drive folder the team already uses.
ACE_DRIVE_ROOT_FOLDER_ID = env(
    "ACE_DRIVE_ROOT_FOLDER_ID",
    default="1HThsA_0Lr5p1OdI5r-aQ446HlNBaySLz",
)

# ACE plugin repo path — the System Overview tab reads skill definitions,
# agent definitions, and the artifact manifest from this directory.
# Also consumed by apps.opps.skills for the dynamic Workbench registry.
#
# In prod the Dockerfile vendors the plugin to /app/vendor/ace. In dev we
# default to BASE_DIR.parent/ace (the sibling-repo layout), but when
# ace-web is checked out inside a git-worktree tree (`.claude/worktrees/<x>`)
# the sibling-repo path doesn't resolve. Walk up looking for a real
# ace plugin dir before falling back.
_DEFAULT_PLUGIN_PATH = BASE_DIR.parent / "ace"
if not _DEFAULT_PLUGIN_PATH.is_dir():
    _candidate = BASE_DIR
    for _ in range(5):
        _candidate = _candidate.parent
        _maybe = _candidate / "ace"
        if _maybe.is_dir() and (_maybe / "agents").is_dir():
            _DEFAULT_PLUGIN_PATH = _maybe
            break
ACE_PLUGIN_PATH = env.str("ACE_PLUGIN_PATH", default=str(_DEFAULT_PLUGIN_PATH))

# --- Django REST Framework ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "apps.auth.token_backend.BearerTokenAuthentication",
    ],
}

# --- Google Drive service account ---
# SA JSON key for the shared ACE Drive (read/write on the Shared Drive
# the SA has been granted access to). The whole JSON blob lives as a
# single string — parsed by apps.opps.drive_client.get_drive_client at
# first use. Sourced from AWS Secrets Manager in prod, .env in dev.
# Empty default: opps views return a 500 with code="drive-not-configured".
ACE_DRIVE_SA_KEY_JSON = env("ACE_DRIVE_SA_KEY_JSON", default="")

# --- Phase 3 dev-only test hooks ---
# Both settings default to False and are only True in development.py.
# They gate hooks that bypass real authentication and the real Claude CLI
# subprocess for automated Playwright E2E testing. See
# docs/learnings/playwright-test-hooks.md for the rationale.
#
# SECURITY: the test-login view and FakeCLIBackend must be impossible to
# reach in production. We belt-and-suspenders this three ways:
#   1. Defaults are False here.
#   2. development.py is the only settings module that sets them True.
#   3. The test-login view AND its URL registration additionally require
#      DEBUG=True, which production.py / connectlabs.py disable.
ACE_ALLOW_TEST_LOGIN = env.bool("ACE_ALLOW_TEST_LOGIN", default=False)
ACE_USE_FAKE_CLI_BACKEND = env.bool("ACE_USE_FAKE_CLI_BACKEND", default=False)

# --- E2E auth token (labs environments) ---
# A pre-shared secret that allows automated tools (walkthroughs, CI) to
# authenticate without going through OAuth. Empty = disabled. The endpoint
# at /auth/e2e-login/ only registers when this is non-empty. Stored in
# AWS Secrets Manager alongside other labs secrets.
ACE_E2E_AUTH_TOKEN = env("ACE_E2E_AUTH_TOKEN", default="")

# --- Allowed email domains ---
ACE_ALLOWED_EMAIL_DOMAINS = ["dimagi.com", "dimagi-ai.com"]

# --- Service Accounts ---
SERVICE_ACCOUNTS = {
    "PROVIDERS": {
        "google_sa": "apps.service_accounts.providers.GoogleSAProvider",
        "api_key": "apps.service_accounts.providers.ApiKeyProvider",
    },
    "BOOTSTRAP_FROM_ENV": {
        "ace-drive": {
            "credential_type": "google_sa",
            "env_var": "ACE_DRIVE_SA_KEY_JSON",
            "default_scopes": ["https://www.googleapis.com/auth/drive"],
        },
    },
}

# --- Logging ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": env("ACE_LOG_LEVEL", default="INFO"),
    },
}
