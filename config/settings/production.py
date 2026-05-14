"""AWS ECS Fargate production settings."""
import os
import warnings

if not os.environ.get("ACE_FIELD_ENCRYPTION_KEY"):
    raise RuntimeError(
        "ACE_FIELD_ENCRYPTION_KEY must be set in production. "
        "Dev/CI may fall back to SECRET_KEY but prod must not."
    )

from .base import *  # noqa: E402, F401, F403

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

# ---------------------------------------------------------------------------
# Structured JSON logging → CloudWatch Logs
#
# Container stdout is captured by ECS's awslogs log driver and lands in the
# CloudWatch log group configured in the task definition (typically
# /ecs/ace-web). JSON formatting makes every record queryable via Logs
# Insights, e.g.:
#
#   fields @timestamp, request_id, level, name, message
#   | filter level = "ERROR"
#   | sort @timestamp desc
#
# ``request_id`` is injected by ``RequestIDMiddleware`` (apps/common/
# logging_middleware.py) which is wired into MIDDLEWARE in base.py.
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {
            "()": "apps.common.logging_middleware.RequestIDFilter",
        },
    },
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s",
            "rename_fields": {"asctime": "timestamp", "levelname": "level"},
            "json_ensure_ascii": False,
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_id"],
        },
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

# ---------------------------------------------------------------------------
# AWS X-Ray distributed tracing
#
# Emits segments to the X-Ray daemon, which should run as a sidecar in the
# ECS task definition. Standard pattern: add an `xray-daemon` container
# (public.ecr.aws/xray/aws-xray-daemon) alongside the app and frontend
# containers, with UDP port 2000 exposed on localhost.
#
# ``context_missing="LOG_ERROR"`` ensures the SDK is non-fatal when no
# daemon is present (e.g. local dev, CI) — it logs an error and continues.
# ---------------------------------------------------------------------------
from aws_xray_sdk.core import patch_all, xray_recorder  # noqa: E402

xray_recorder.configure(
    service="ace-web",
    daemon_address=os.environ.get("AWS_XRAY_DAEMON_ADDRESS", "127.0.0.1:2000"),
    context_missing="LOG_ERROR",  # don't crash when no daemon is reachable
)
patch_all()  # instruments httpx, requests, psycopg, boto3, etc.

# X-Ray Django middleware — prepend so it wraps all other middleware.
MIDDLEWARE = ["aws_xray_sdk.ext.django.middleware.XRayMiddleware"] + MIDDLEWARE  # noqa: F405
