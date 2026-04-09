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
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
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
CONNECT_OAUTH_SCOPES = ["read"]

# Django auth wiring
LOGIN_URL = "/auth/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/auth/login/"

# --- Claude CLI integration (Phase 2) ---
ACE_CLAUDE_HOME = env(
    "ACE_CLAUDE_HOME",
    default=str(BASE_DIR / ".ace-claude-home"),
)
ACE_CLAUDE_TOKEN_FILE = env(
    "ACE_CLAUDE_TOKEN_FILE",
    default=str(BASE_DIR / ".ace-claude-home" / "oauth-token"),
)

# --- Google Drive OAuth (secondary flow for the Workbench) ---
# Encryption key for the per-user Drive token cache. Rotated via AWS Secrets
# Manager / SSM Parameter Store in prod. In dev, a static key is fine.
ACE_DRIVE_TOKEN_ENCRYPTION_KEY = env(
    "ACE_DRIVE_TOKEN_ENCRYPTION_KEY",
    default="dev-insecure-drive-token-key-change-me",
)
# Google OAuth client credentials (registered in the dimagi GCP console with
# redirect URIs for both dev and prod). Same OAuth project connect-search uses
# unless there is a reason to mint a new one.
ACE_GOOGLE_OAUTH_CLIENT_ID = env("ACE_GOOGLE_OAUTH_CLIENT_ID", default="")
ACE_GOOGLE_OAUTH_CLIENT_SECRET = env("ACE_GOOGLE_OAUTH_CLIENT_SECRET", default="")
# Redirect URI the callback view builds. Relative to SITE_URL — dev default
# is local Django, prod is the AWS tenant under /ace/.
ACE_DRIVE_OAUTH_REDIRECT_URI = env(
    "ACE_DRIVE_OAUTH_REDIRECT_URI",
    default="http://localhost:8000/auth/drive/callback",
)
# Scopes requested for Drive access. Read-only — the Workbench never writes.
ACE_DRIVE_OAUTH_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]
# Top-level Drive folder that holds ACE opportunities. Default matches the
# ACE plugin convention.
ACE_DRIVE_ROOT_FOLDER_NAME = env("ACE_DRIVE_ROOT_FOLDER_NAME", default="ACE")

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
