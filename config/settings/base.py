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
    "apps.activity.apps.ActivityConfig",
    "apps.mobile.apps.MobileConfig",
    "apps.videos.apps.VideosConfig",
    "apps.slack.apps.SlackConfig",
    "apps.canopy",
    "apps.presence.apps.PresenceConfig",
]

AUTH_USER_MODEL = "ace_auth.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.common.logging_middleware.RequestIDMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.auth.middleware.BearerTokenAuthMiddleware",
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

# --- Cache ---
# Use the same Redis the Channel layer uses, namespaced under db=1 so a
# cache flush doesn't blow away pub/sub state. Backing the Drive cache
# (apps/opps/drive_cache.py) with Redis (vs Django's default LocMem)
# means consecutive page loads survive uvicorn `--reload` in dev and
# any future multi-worker prod deploy.
#
# Falls back to LocMem when REDIS_URL is empty (test envs override this
# in config/settings/test.py anyway).
if REDIS_URL:
    _cache_url = REDIS_URL
    if "?db=" not in _cache_url and "/0" in _cache_url:  # pyright: ignore[reportOperatorIssue]
        _cache_url = _cache_url.replace("/0", "/1", 1)
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _cache_url,
            "TIMEOUT": 30,
        },
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        },
    }

# Drive cache TTL — short enough that operator edits in Drive show up
# within ~30 s without a hard refresh, long enough that consecutive page
# loads land in single-digit ms. Pass ``?force=1`` on any opps endpoint
# to bypass and rebuild from Drive.
OPPS_DRIVE_CACHE_SECONDS = env.int("OPPS_DRIVE_CACHE_SECONDS", default=30)

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

# --- Connect OAuth (labs / AWS deployment) ---
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
# Migration-only seed value for the founding workspace's Drive folder.
# Read by apps/workspaces/migrations/0002_seed_dimagi_team.py to populate
# the dimagi-team workspace once at bootstrap; not read at runtime.
# Per-workspace Drive folders are stored on Workspace.drive_root_folder_id
# (post-2026-04-27 multi-tenancy work). Empty default is safe — the
# migration skips the seed when this is unset.
ACE_DRIVE_ROOT_FOLDER_ID = env("ACE_DRIVE_ROOT_FOLDER_ID", default="")

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

# --- Videos (clip-explorer) ---
# Root of the connect-videos Node project that ships the clip-explorer
# tooling. Django reads through to its programs/*.yaml and the generated
# out/clip-explorer/<slug>/ artifacts; renders shell out to its
# `npm run …` scripts. Default points at the bundled checkout under this
# repo; override in CI/sandbox setups via the env var.
ACE_VIDEOS_ROOT = env.str(
    "ACE_VIDEOS_ROOT",
    default=str(BASE_DIR / "video-production" / "connect-videos"),
)

# --- Google Drive service account ---
# SA JSON key for the shared ACE Drive (read/write on the Shared Drive
# the SA has been granted access to). The whole JSON blob lives as a
# single string — parsed by apps.opps.drive_client.get_drive_client at
# first use. Sourced from AWS Secrets Manager in prod, .env in dev.
# Empty default: opps views return a 500 with code="drive-not-configured".
ACE_DRIVE_SA_KEY_JSON = env("ACE_DRIVE_SA_KEY_JSON", default="")

# --- Mobile cloud runner (POC) ---
# Single EC2 instance + S3 bucket provisioned by infra/mobile/ Terraform.
# The EmulatorController in apps.mobile.controller drives them via boto3
# (SSM Session Manager for in-VM exec, no SSH). Empty defaults so a
# deploy without these env vars 503s with a clear "not-configured" error
# rather than failing mid-call.
#
# Set in deploy/aws/ace-web.cfn.yaml after `terraform apply` emits
# the values from infra/mobile/outputs.tf.
ACE_MOBILE_AWS_REGION = env("ACE_MOBILE_AWS_REGION", default="us-east-1")
ACE_MOBILE_INSTANCE_ID = env("ACE_MOBILE_INSTANCE_ID", default="")
ACE_MOBILE_S3_BUCKET = env("ACE_MOBILE_S3_BUCKET", default="")
ACE_MOBILE_AMI_VERSION = env("ACE_MOBILE_AMI_VERSION", default="")

# --- Chat subprocess back-channel ---
# Public-facing base URL of this ace-web deployment, including the
# /ace path prefix when one is in use. The chat subprocess gets this
# in its env (alongside a per-session PersonalToken) so the bundled
# ACE plugin can POST back for upload-transcript and call /api/mobile/
# for cloud-emulator-driven flows. Empty disables the staging — the
# plugin's smart-default then silently skips back-channel calls. Set
# in deploy/aws/ace-web.cfn.yaml for labs; defaults to the local
# docker-compose port for dev.
ACE_WEB_BASE_URL = env("ACE_WEB_BASE_URL", default="")

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

# --- Slack integration ---
SLACK_CLIENT_ID = env("SLACK_CLIENT_ID", default="")
SLACK_CLIENT_SECRET = env("SLACK_CLIENT_SECRET", default="")
SLACK_SIGNING_SECRET = env("SLACK_SIGNING_SECRET", default="")
SLACK_DEFAULT_INSTALLATION_ID = env("SLACK_DEFAULT_INSTALLATION_ID", default="")
ACE_PUBLIC_BASE_URL = env("ACE_PUBLIC_BASE_URL",
                          default="https://labs.connect.dimagi.com/ace")

# --- canopy-web hosted chat (Part 2 cutover; spec lives in canopy-web) -------
# Server-side base for outbound calls (token exchange, session create).
CANOPY_BASE_URL = env("CANOPY_BASE_URL", default="")
# Registered AppCredential raw value (canopy: manage.py create_app_credential).
CANOPY_APP_CREDENTIAL = env("CANOPY_APP_CREDENTIAL", default="")
# Browser-facing base: same-origin path prefix on labs, vite proxy path in dev.
CANOPY_PUBLIC_BASE_URL = env("CANOPY_PUBLIC_BASE_URL", default="/canopy")
CANOPY_WORKSPACE = env("CANOPY_WORKSPACE", default="connect")
CANOPY_AGENT_SLUG = env("CANOPY_AGENT_SLUG", default="ace")

# Run execution on canopy's harness (spec: canopy-web
# docs/superpowers/specs/2026-07-26-run-execution-convergence-design.md).
# OFF by default and it must stay off until a SESSION-CAPABLE canopy runner
# exists: with none online, every enqueued turn sits QUEUED forever, so
# flipping this on takes ACE runs from "works" to "nothing runs".
CANOPY_RUN_EXECUTION = env.bool("CANOPY_RUN_EXECUTION", default=False)
# Whose canopy identity a run acts as when the owning ace-web user's email is
# not delegable (canopy's token-exchange 403s a domain outside the app
# credential's allowed_delegation_domains). Empty = no fallback: dispatch
# fails loudly rather than silently attributing one human's run to another.
CANOPY_RUN_ACTOR_FALLBACK_EMAIL = env("CANOPY_RUN_ACTOR_FALLBACK_EMAIL", default="")
# Ceiling on a single turn transcript fetched from canopy. canopy's own per-turn
# cap is 100 MB; this is ace-web's defensive limit on what it will pull into a
# web worker's memory to re-derive cost/structure from.
CANOPY_TRANSCRIPT_MAX_BYTES = env.int("CANOPY_TRANSCRIPT_MAX_BYTES", default=64 * 1024 * 1024)

# --- Allowed email domains ---
# Empty list = allow any Connect-authenticated user. Workspace memberships
# are the actual access-control gate; the domain filter is preserved as a
# deployment safety knob (set to a non-empty list to revert to allow-listed
# signups).
ACE_ALLOWED_EMAIL_DOMAINS = env.list("ACE_ALLOWED_EMAIL_DOMAINS", default=[])

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
