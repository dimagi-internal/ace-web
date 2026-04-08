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
]

AUTH_USER_MODEL = "ace_auth.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.auth.middleware.IAPHeaderAuthMiddleware",
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
STATICFILES_DIRS = [BASE_DIR / "frontend" / "dist"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# --- Auth / IAP ---
IAP_HEADER_EMAIL = "HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL"
IAP_HEADER_USER_ID = "HTTP_X_GOOG_AUTHENTICATED_USER_ID"
IAP_REQUIRED = env.bool("ACE_IAP_REQUIRED", default=False)
# When IAP_REQUIRED is False (dev), middleware accepts a fake header for local dev.
IAP_DEV_FAKE_EMAIL = env("ACE_IAP_DEV_FAKE_EMAIL", default="dev@example.com")
IAP_DEV_FAKE_USER_ID = env("ACE_IAP_DEV_FAKE_USER_ID", default="dev-user-1")

# --- I18N ---
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Claude CLI integration (Phase 2) ---
ACE_CLAUDE_HOME = env(
    "ACE_CLAUDE_HOME",
    default=str(BASE_DIR / ".ace-claude-home"),
)
ACE_CLAUDE_TOKEN_FILE = env(
    "ACE_CLAUDE_TOKEN_FILE",
    default=str(BASE_DIR / ".ace-claude-home" / "oauth-token"),
)

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
