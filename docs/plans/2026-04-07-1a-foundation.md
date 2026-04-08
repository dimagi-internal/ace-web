# ACE Web Harness — Plan 1A: Foundation

> **Status: COMPLETE (2026-04-07).** Executed via subagent-driven-development. Tasks 1–10 implemented and committed; Task 11 (manual GCP deploy) is pending user action.
>
> **If you are re-running this plan from scratch**, ALSO apply the 15 fixes documented in the "Post-execution corrections" section at the bottom of this file. They were identified by per-task and whole-plan code reviews and cover several real security bugs, schema mistakes, and cross-task integration issues that the original plan shipped with.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a deployable Django + Channels + React skeleton on GCP Cloud Run with Postgres, IAP-based auth, and the full data model migrated. At the end of this plan, you can hit `https://<cloud-run-url>/health` after Google SSO and see a 200, and all database tables exist. No chat functionality yet — that's Plan 1B.

**Architecture:** Django 5 (ASGI via uvicorn) + Channels for WebSocket layer (no consumers yet, just plumbing) + DRF for REST + Postgres in Cloud SQL. React 19 + Vite + Tailwind frontend, built static and served via WhiteNoise. Custom Django User populated from GCP IAP headers (`X-Goog-Authenticated-User-Email`, `X-Goog-Authenticated-User-ID`). Same general layout as `canopy-web` so we can lift patterns wholesale.

**Tech Stack:** Python 3.11+, Django 5.x, Django Channels 4, Django REST Framework, uvicorn, psycopg[binary], WhiteNoise, React 19, Vite, TypeScript, Tailwind CSS 4, pytest + pytest-django + pytest-asyncio, Docker, GCP Cloud Run + Cloud SQL + Secret Manager + IAP.

**Repo location:** `/Users/jjackson/emdash-projects/ace-web/` (new repo, separate from `ace/`, `canopy/`, and `canopy-web/`).

**Reference for canopy-web patterns:** `/Users/jjackson/emdash-projects/canopy-web/` — copy structure from `apps/common/anthropic_client.py`, `apps/common/auth_flow.py`, `apps/common/envelope.py`, `config/settings/base.py`, `config/asgi.py`, `Dockerfile`, `entrypoint.sh`, `docker-compose.yml`.

---

## File structure (created across all tasks)

```
ace-web/
├── pyproject.toml
├── README.md
├── .gitignore
├── .env.example
├── manage.py
├── Dockerfile
├── Dockerfile.frontend           # only if we go nginx-sidecar route; default: skip, use WhiteNoise
├── docker-compose.yml
├── entrypoint.sh
├── cloudbuild.yaml               # GCP Cloud Build config for Cloud Run deploy
│
├── config/
│   ├── __init__.py
│   ├── asgi.py                   # ASGI app with Channels routing
│   ├── wsgi.py                   # WSGI fallback (not used in prod)
│   ├── urls.py                   # Top-level URL routing
│   └── settings/
│       ├── __init__.py
│       ├── base.py               # Shared settings
│       ├── development.py        # Local dev (SQLite or local Postgres)
│       ├── production.py         # Cloud Run (Cloud SQL via Unix socket)
│       └── test.py               # Pytest settings (in-memory SQLite/Postgres)
│
├── apps/
│   ├── __init__.py
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── models.py             # Custom User model
│   │   ├── middleware.py         # IAPHeaderAuthMiddleware
│   │   ├── admin.py
│   │   ├── migrations/
│   │   │   ├── __init__.py
│   │   │   └── 0001_initial.py
│   │   └── tests/
│   │       ├── __init__.py
│   │       ├── test_models.py
│   │       └── test_middleware.py
│   │
│   ├── sessions/
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── models.py             # Session, SessionParticipant, Message, Draft, ShareToken, IngestUpload
│   │   ├── admin.py
│   │   ├── migrations/
│   │   │   ├── __init__.py
│   │   │   └── 0001_initial.py
│   │   └── tests/
│   │       ├── __init__.py
│   │       └── test_models.py
│   │
│   └── common/
│       ├── __init__.py
│       ├── apps.py
│       ├── envelope.py           # Response wrapper {data, error}
│       ├── views.py              # health_check view
│       └── tests/
│           ├── __init__.py
│           └── test_health.py
│
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── index.html
│   ├── public/                   # static assets
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── router.tsx
│       ├── pages/
│       │   ├── HomePage.tsx
│       │   └── HealthPage.tsx
│       ├── api/
│       │   └── client.ts
│       └── styles/
│           └── globals.css
│
└── tests/
    ├── __init__.py
    └── conftest.py
```

After Plan 1A: Plan 1B adds `apps/chat/` (ChatBackend interface + CLIBackend) and a chat REST API. Plan 1C adds `apps/sessions/consumers.py` and the WebSocket layer. Plan 1D adds `apps/ingest/` and the `ace upload` CLI.

---

## Task 1: Initialize project repo

**Files:**
- Create: `/Users/jjackson/emdash-projects/ace-web/.gitignore`
- Create: `/Users/jjackson/emdash-projects/ace-web/README.md`
- Create: `/Users/jjackson/emdash-projects/ace-web/pyproject.toml`

- [ ] **Step 1: Create the directory and initialize git**

```bash
mkdir -p /Users/jjackson/emdash-projects/ace-web
cd /Users/jjackson/emdash-projects/ace-web
git init
```

Expected: `Initialized empty Git repository in /Users/jjackson/emdash-projects/ace-web/.git/`

- [ ] **Step 2: Write `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
env/
*.egg-info/
.pytest_cache/
.mypy_cache/
.coverage
htmlcov/
dist/
build/

# Django
*.log
local_settings.py
db.sqlite3
db.sqlite3-journal
media/
staticfiles/

# Node
node_modules/
frontend/dist/
.DS_Store
.env
.env.local

# IDE
.vscode/
.idea/

# Secrets
*.pem
oauth-token
claude-data/
```

- [ ] **Step 3: Write `README.md`**

```markdown
# ace-web

The web harness for the ACE (AI Connect Engine / CRISPR-Connect) initiative.

Module 1 of the larger ACE web system. See `ace/docs/superpowers/specs/2026-04-07-ace-web-harness-design.md` for the full design.

## Quick start (local dev)

```bash
docker compose up
```

Then open http://localhost:8000.

## Stack

- Django 5 + Channels + DRF (ASGI via uvicorn)
- React 19 + Vite + Tailwind 4
- PostgreSQL
- Deployed on GCP Cloud Run + Cloud SQL behind IAP
```

- [ ] **Step 4: Write `pyproject.toml`**

```toml
[project]
name = "ace-web"
version = "0.1.0"
description = "Web harness for the ACE initiative"
requires-python = ">=3.11"
dependencies = [
    "django>=5.0,<6.0",
    "djangorestframework>=3.15",
    "channels>=4.1",
    "daphne>=4.1",                 # ASGI dev server; uvicorn used in prod
    "uvicorn[standard]>=0.30",
    "psycopg[binary]>=3.2",
    "whitenoise>=6.7",
    "django-environ>=0.11",
    "pydantic>=2.7",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-django>=4.8",
    "pytest-asyncio>=0.23",
    "ruff>=0.5",
    "ipython",
]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings.test"
python_files = "test_*.py"
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B"]
```

- [ ] **Step 5: Create a virtual environment and install deps**

```bash
cd /Users/jjackson/emdash-projects/ace-web
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: deps install cleanly. `python -c "import django; print(django.get_version())"` should print `5.x.x`.

- [ ] **Step 6: Commit**

```bash
git add .gitignore README.md pyproject.toml
git commit -m "chore: initialize ace-web repo with Django stack"
```

---

## Task 2: Django project skeleton with split settings

**Files:**
- Create: `/Users/jjackson/emdash-projects/ace-web/manage.py`
- Create: `/Users/jjackson/emdash-projects/ace-web/config/__init__.py`
- Create: `/Users/jjackson/emdash-projects/ace-web/config/settings/__init__.py`
- Create: `/Users/jjackson/emdash-projects/ace-web/config/settings/base.py`
- Create: `/Users/jjackson/emdash-projects/ace-web/config/settings/development.py`
- Create: `/Users/jjackson/emdash-projects/ace-web/config/settings/production.py`
- Create: `/Users/jjackson/emdash-projects/ace-web/config/settings/test.py`
- Create: `/Users/jjackson/emdash-projects/ace-web/config/urls.py`
- Create: `/Users/jjackson/emdash-projects/ace-web/config/asgi.py`
- Create: `/Users/jjackson/emdash-projects/ace-web/config/wsgi.py`

- [ ] **Step 1: Write `manage.py`**

```python
#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Is it installed and the venv activated?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
```

Make it executable:

```bash
chmod +x manage.py
```

- [ ] **Step 2: Create `config/` package structure**

```bash
mkdir -p config/settings
touch config/__init__.py config/settings/__init__.py
```

- [ ] **Step 3: Write `config/settings/base.py`**

```python
"""Shared Django settings for ace-web."""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

# --- Core ---
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])

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
```

- [ ] **Step 4: Write `config/settings/development.py`**

```python
"""Local development settings."""
from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["*"]
IAP_REQUIRED = False
```

- [ ] **Step 5: Write `config/settings/production.py`**

```python
"""Cloud Run production settings."""
import os

from .base import *  # noqa: F401, F403

DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[".run.app"])  # noqa: F405
IAP_REQUIRED = True

# Cloud SQL via Unix socket when CLOUD_SQL_CONNECTION_NAME is set
CLOUD_SQL = os.environ.get("CLOUD_SQL_CONNECTION_NAME")
if CLOUD_SQL:
    DATABASES["default"]["HOST"] = f"/cloudsql/{CLOUD_SQL}"  # noqa: F405

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

- [ ] **Step 6: Write `config/settings/test.py`**

```python
"""Pytest settings."""
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
```

- [ ] **Step 7: Write `config/urls.py`**

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.common.urls")),
]
```

- [ ] **Step 8: Write `config/asgi.py`**

```python
"""ASGI entry point with Channels routing."""
import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

django_asgi_app = get_asgi_application()

# Plan 1C will populate this with WebSocket routes from apps/sessions/routing.py
websocket_urlpatterns: list = []

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(URLRouter(websocket_urlpatterns)),
    }
)
```

- [ ] **Step 9: Write `config/wsgi.py`**

```python
"""WSGI fallback. Production uses ASGI via uvicorn; this exists for tooling compatibility."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

application = get_wsgi_application()
```

- [ ] **Step 10: Verify Django sees the project**

```bash
DJANGO_SETTINGS_MODULE=config.settings.development python -c "import django; django.setup(); from django.conf import settings; print(settings.INSTALLED_APPS)"
```

Expected: list of installed apps prints (with `apps.common`, `apps.auth.apps.AuthConfig`, `apps.sessions.apps.SessionsConfig` — these will fail to import until Tasks 3-5, which is fine for now; remove the `apps.*` lines from `INSTALLED_APPS` temporarily if you want to verify, then restore them).

- [ ] **Step 11: Commit**

```bash
git add manage.py config/
git commit -m "chore: scaffold Django project with split settings and ASGI"
```

---

## Task 3: Common app with health check endpoint

**Files:**
- Create: `apps/__init__.py`
- Create: `apps/common/__init__.py`
- Create: `apps/common/apps.py`
- Create: `apps/common/envelope.py`
- Create: `apps/common/views.py`
- Create: `apps/common/urls.py`
- Create: `apps/common/tests/__init__.py`
- Create: `apps/common/tests/test_health.py`

- [ ] **Step 1: Create the app package**

```bash
mkdir -p apps/common/tests
touch apps/__init__.py apps/common/__init__.py apps/common/tests/__init__.py
```

- [ ] **Step 2: Write `apps/common/apps.py`**

```python
from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"
```

- [ ] **Step 3: Write `apps/common/envelope.py`**

```python
"""Standard envelope for JSON API responses, adapted from canopy-web."""
from typing import Any


def success_response(data: Any) -> dict[str, Any]:
    return {"data": data, "error": None}


def error_response(message: str, code: str = "error") -> dict[str, Any]:
    return {"data": None, "error": {"code": code, "message": message}}
```

- [ ] **Step 4: Write the failing test for the health endpoint**

```python
# apps/common/tests/test_health.py
import pytest
from django.test import Client


@pytest.mark.django_db
def test_health_returns_ok():
    client = Client()
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "ok"
    assert body["error"] is None
```

- [ ] **Step 5: Run the test to verify it fails**

```bash
pytest apps/common/tests/test_health.py -v
```

Expected: FAIL — `/api/health` 404s because no view exists yet.

- [ ] **Step 6: Implement `apps/common/views.py`**

```python
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .envelope import success_response


@require_GET
def health_check(request):
    return JsonResponse(success_response({"status": "ok"}))
```

- [ ] **Step 7: Implement `apps/common/urls.py`**

```python
from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health_check, name="health"),
]
```

- [ ] **Step 8: Run the test to verify it passes**

```bash
pytest apps/common/tests/test_health.py -v
```

Expected: PASS.

- [ ] **Step 9: Smoke test the dev server**

```bash
DJANGO_SETTINGS_MODULE=config.settings.development python manage.py runserver 8000 &
sleep 2
curl -s http://localhost:8000/api/health
kill %1
```

Expected: `{"data": {"status": "ok"}, "error": null}`

- [ ] **Step 10: Commit**

```bash
git add apps/__init__.py apps/common/
git commit -m "feat(common): add health check endpoint with envelope wrapper"
```

---

## Task 4: Auth app — custom User model and IAP middleware

**Files:**
- Create: `apps/auth/__init__.py`
- Create: `apps/auth/apps.py`
- Create: `apps/auth/models.py`
- Create: `apps/auth/managers.py`
- Create: `apps/auth/middleware.py`
- Create: `apps/auth/admin.py`
- Create: `apps/auth/tests/__init__.py`
- Create: `apps/auth/tests/test_models.py`
- Create: `apps/auth/tests/test_middleware.py`

- [ ] **Step 1: Create the app package**

```bash
mkdir -p apps/auth/tests apps/auth/migrations
touch apps/auth/__init__.py apps/auth/tests/__init__.py apps/auth/migrations/__init__.py
```

- [ ] **Step 2: Write `apps/auth/apps.py`**

```python
from django.apps import AppConfig


class AuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.auth"
    label = "ace_auth"  # avoid clash with django.contrib.auth
```

- [ ] **Step 3: Write `apps/auth/managers.py`**

```python
from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email: str, display_name: str = "", google_sub: str = ""):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(
            email=email,
            display_name=display_name or email.split("@")[0],
            google_sub=google_sub,
        )
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None):
        user = self.create_user(email=email, display_name=email.split("@")[0])
        user.is_staff = True
        user.is_superuser = True
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user
```

- [ ] **Step 4: Write `apps/auth/models.py`**

```python
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=200)
    google_sub = models.CharField(max_length=200, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.email
```

- [ ] **Step 5: Write the failing test for the User model**

```python
# apps/auth/tests/test_models.py
import pytest

from apps.auth.models import User


@pytest.mark.django_db
def test_create_user_normalizes_email_and_sets_unusable_password():
    user = User.objects.create_user(email="JJ@Example.com", display_name="Jonathan")
    assert user.email == "JJ@example.com"
    assert user.display_name == "Jonathan"
    assert not user.has_usable_password()


@pytest.mark.django_db
def test_email_is_unique():
    User.objects.create_user(email="a@b.c")
    with pytest.raises(Exception):
        User.objects.create_user(email="a@b.c")
```

- [ ] **Step 6: Generate and run the migration**

```bash
DJANGO_SETTINGS_MODULE=config.settings.development python manage.py makemigrations ace_auth
```

Expected: creates `apps/auth/migrations/0001_initial.py`.

- [ ] **Step 7: Run the User model tests**

```bash
pytest apps/auth/tests/test_models.py -v
```

Expected: PASS.

- [ ] **Step 8: Write `apps/auth/middleware.py`**

```python
"""IAP header authentication middleware.

Reads X-Goog-Authenticated-User-Email and X-Goog-Authenticated-User-ID
headers from GCP IAP and either finds or creates the corresponding User row.

In dev (when IAP_REQUIRED is False), accepts a fake header injected from
settings to enable local development without IAP.
"""
import logging
from typing import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from .models import User

logger = logging.getLogger(__name__)


class IAPHeaderAuthMiddleware:
    """Populate request.user from IAP headers, or fail closed if IAP is required."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path == "/api/health":
            # Health check is always public; Cloud Run probes need to hit it.
            return self.get_response(request)

        email, google_sub = self._extract_identity(request)
        if not email:
            if settings.IAP_REQUIRED:
                return JsonResponse(
                    {"data": None, "error": {"code": "unauthenticated", "message": "IAP headers missing"}},
                    status=401,
                )
            email = settings.IAP_DEV_FAKE_EMAIL
            google_sub = settings.IAP_DEV_FAKE_USER_ID

        user = self._get_or_create_user(email=email, google_sub=google_sub)
        request.user = user
        return self.get_response(request)

    def _extract_identity(self, request: HttpRequest) -> tuple[str | None, str | None]:
        raw_email = request.META.get(settings.IAP_HEADER_EMAIL, "")
        raw_sub = request.META.get(settings.IAP_HEADER_USER_ID, "")
        # IAP prefixes the value with "accounts.google.com:"
        email = raw_email.split(":", 1)[-1] if raw_email else None
        sub = raw_sub.split(":", 1)[-1] if raw_sub else None
        return (email or None), (sub or None)

    def _get_or_create_user(self, *, email: str, google_sub: str | None) -> User:
        try:
            user = User.objects.get(email=email)
            if google_sub and not user.google_sub:
                user.google_sub = google_sub
                user.save(update_fields=["google_sub"])
            return user
        except User.DoesNotExist:
            return User.objects.create_user(
                email=email,
                display_name=email.split("@")[0],
                google_sub=google_sub or "",
            )
```

- [ ] **Step 9: Write the failing test for the middleware**

```python
# apps/auth/tests/test_middleware.py
import pytest
from django.test import Client, override_settings

from apps.auth.models import User


@pytest.mark.django_db
def test_health_endpoint_skips_auth():
    """Health check should not require auth even with IAP_REQUIRED=True."""
    with override_settings(IAP_REQUIRED=True):
        client = Client()
        response = client.get("/api/health")
        assert response.status_code == 200


@pytest.mark.django_db
def test_iap_required_blocks_unauthenticated():
    """When IAP_REQUIRED is True, requests without IAP headers get 401."""
    with override_settings(IAP_REQUIRED=True):
        client = Client()
        # Create a fake protected endpoint by hitting admin (which requires auth)
        response = client.get("/admin/")
        # IAP middleware returns 401 before Django auth kicks in
        assert response.status_code == 401


@pytest.mark.django_db
def test_iap_creates_user_on_first_sight():
    """First request with IAP headers creates the User row."""
    assert not User.objects.filter(email="new@example.com").exists()
    with override_settings(IAP_REQUIRED=True):
        client = Client()
        response = client.get(
            "/api/health",
            HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL="accounts.google.com:new@example.com",
            HTTP_X_GOOG_AUTHENTICATED_USER_ID="accounts.google.com:abc123",
        )
        # Health doesn't require auth so it always succeeds, but the middleware
        # also doesn't run on /api/health. Test creation via a different path.
        assert response.status_code == 200

    # Now hit a path that does run middleware
    with override_settings(IAP_REQUIRED=True):
        client = Client()
        client.get(
            "/admin/login/",
            HTTP_X_GOOG_AUTHENTICATED_USER_EMAIL="accounts.google.com:new@example.com",
            HTTP_X_GOOG_AUTHENTICATED_USER_ID="accounts.google.com:abc123",
        )
        assert User.objects.filter(email="new@example.com").exists()
        user = User.objects.get(email="new@example.com")
        assert user.google_sub == "abc123"


@pytest.mark.django_db
def test_iap_dev_fake_email_when_not_required():
    """When IAP is not required, dev fake email is used."""
    with override_settings(IAP_REQUIRED=False, IAP_DEV_FAKE_EMAIL="dev@example.com"):
        client = Client()
        client.get("/admin/login/")
        assert User.objects.filter(email="dev@example.com").exists()
```

- [ ] **Step 10: Run the middleware tests**

```bash
pytest apps/auth/tests/test_middleware.py -v
```

Expected: PASS.

- [ ] **Step 11: Write `apps/auth/admin.py`**

```python
from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "display_name", "is_active", "is_staff", "created_at")
    search_fields = ("email", "display_name")
    readonly_fields = ("created_at", "updated_at")
```

- [ ] **Step 12: Run the full test suite to make sure nothing else broke**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 13: Commit**

```bash
git add apps/auth/
git commit -m "feat(auth): add custom User model and IAP header middleware"
```

---

## Task 5: Sessions app — all data model tables

**Files:**
- Create: `apps/sessions/__init__.py`
- Create: `apps/sessions/apps.py`
- Create: `apps/sessions/models.py`
- Create: `apps/sessions/admin.py`
- Create: `apps/sessions/migrations/__init__.py`
- Create: `apps/sessions/tests/__init__.py`
- Create: `apps/sessions/tests/test_models.py`

- [ ] **Step 1: Create the app package**

```bash
mkdir -p apps/sessions/tests apps/sessions/migrations
touch apps/sessions/__init__.py apps/sessions/tests/__init__.py apps/sessions/migrations/__init__.py
```

- [ ] **Step 2: Write `apps/sessions/apps.py`**

```python
from django.apps import AppConfig


class SessionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sessions"
    label = "ace_sessions"  # avoid clash with django.contrib.sessions
```

- [ ] **Step 3: Write `apps/sessions/models.py`**

```python
"""Data models for the ACE web harness sessions, messages, and drafts.

These models are designed to be:
- Append-only for messages (no edits after status='complete')
- Multi-player native (many-to-many user-session via SessionParticipant)
- Extensible to future modules via nullable opportunity_id, ocs_agent_id, idd_ref
"""
import secrets

from django.conf import settings
from django.db import models


def generate_slug() -> str:
    """8-character URL-safe random slug for sessions."""
    return secrets.token_urlsafe(6)[:8]


def generate_share_token() -> str:
    return secrets.token_urlsafe(24)


class Session(models.Model):
    BACKEND_KIND_CHOICES = [
        ("cli", "CLI (subscription)"),
        ("api", "API (key)"),
        ("mcp", "MCP-augmented API"),
    ]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("archived", "Archived"),
        ("imported", "Imported"),
    ]
    SOURCE_CHOICES = [
        ("web", "Web"),
        ("upload", "Upload"),
    ]

    slug = models.CharField(max_length=32, unique=True, default=generate_slug)
    title = models.CharField(max_length=500, blank=True, default="")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_sessions"
    )
    backend_kind = models.CharField(max_length=16, choices=BACKEND_KIND_CHOICES, default="cli")
    backend_config = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active")
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default="web")

    # Placeholders for future modules. All nullable so adding modules later
    # does not require a schema migration.
    opportunity_id = models.BigIntegerField(null=True, blank=True)
    ocs_agent_id = models.CharField(max_length=200, null=True, blank=True)
    idd_ref = models.CharField(max_length=500, null=True, blank=True)
    cli_session_id = models.CharField(max_length=200, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sessions"
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["owner", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.slug}: {self.title or '(untitled)'}"


class SessionParticipant(models.Model):
    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("editor", "Editor"),
        ("viewer", "Viewer"),
    ]

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="session_memberships"
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default="editor")
    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "session_participants"
        constraints = [
            models.UniqueConstraint(fields=["session", "user"], name="unique_participant"),
        ]
        indexes = [
            models.Index(fields=["session", "last_seen_at"]),
        ]


class Message(models.Model):
    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
        ("system", "System"),
        ("tool_use", "Tool use"),
        ("tool_result", "Tool result"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("streaming", "Streaming"),
        ("complete", "Complete"),
        ("error", "Error"),
    ]

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="messages")
    turn_index = models.IntegerField()
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_messages",
    )
    content = models.JSONField()
    plaintext = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    error_detail = models.TextField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "messages"
        constraints = [
            models.UniqueConstraint(
                fields=["session", "turn_index"], name="unique_session_turn"
            ),
        ]
        ordering = ["session_id", "turn_index"]
        indexes = [
            models.Index(fields=["session", "turn_index"]),
        ]


class Draft(models.Model):
    SLOT_CHOICES = [
        ("next", "Next"),
        ("queued", "Queued"),
    ]
    STATUS_CHOICES = [
        ("open", "Open"),
        ("sent", "Sent"),
        ("discarded", "Discarded"),
    ]

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="drafts")
    creator_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_drafts"
    )
    slot = models.CharField(max_length=8, choices=SLOT_CHOICES, default="queued")
    queue_position = models.IntegerField(null=True, blank=True)
    body = models.TextField(blank=True, default="")
    version = models.IntegerField(default=0)
    last_editor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="edited_drafts"
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="open")
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_message = models.ForeignKey(
        Message, on_delete=models.SET_NULL, null=True, blank=True, related_name="from_draft"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "drafts"
        constraints = [
            # Only one open "next" draft per session.
            models.UniqueConstraint(
                fields=["session"],
                condition=models.Q(slot="next", status="open"),
                name="one_next_per_session",
            ),
        ]


class ShareToken(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="share_tokens")
    token = models.CharField(max_length=64, unique=True, default=generate_share_token)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="share_tokens"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "share_tokens"


class IngestUpload(models.Model):
    session = models.ForeignKey(
        Session, on_delete=models.CASCADE, related_name="ingest_records"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploads"
    )
    source_path = models.CharField(max_length=1000, blank=True, default="")
    raw_bytes = models.BigIntegerField(default=0)
    line_count = models.IntegerField(default=0)
    cli_session_id = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingest_uploads"
```

- [ ] **Step 4: Generate the migration**

```bash
DJANGO_SETTINGS_MODULE=config.settings.development python manage.py makemigrations ace_sessions
```

Expected: creates `apps/sessions/migrations/0001_initial.py`.

- [ ] **Step 5: Apply the migration to the dev DB to verify it runs**

```bash
DJANGO_SETTINGS_MODULE=config.settings.development python manage.py migrate
```

Expected: all migrations apply cleanly. (Both `ace_auth` and `ace_sessions` get created.)

- [ ] **Step 6: Write the failing test for the models**

```python
# apps/sessions/tests/test_models.py
import pytest
from django.db import IntegrityError

from apps.auth.models import User
from apps.sessions.models import (
    Draft,
    IngestUpload,
    Message,
    Session,
    SessionParticipant,
    ShareToken,
)


@pytest.fixture
def user(db):
    return User.objects.create_user(email="test@example.com")


@pytest.fixture
def session(user):
    return Session.objects.create(owner=user, title="Test session")


def test_session_slug_is_auto_generated(session):
    assert session.slug
    assert len(session.slug) >= 6


def test_session_default_backend_kind(session):
    assert session.backend_kind == "cli"


def test_session_participant_uniqueness(session, user):
    SessionParticipant.objects.create(session=session, user=user, role="owner")
    with pytest.raises(IntegrityError):
        SessionParticipant.objects.create(session=session, user=user, role="editor")


def test_message_turn_index_is_unique_per_session(session, user):
    Message.objects.create(
        session=session,
        turn_index=0,
        role="user",
        sender_user=user,
        content=[{"type": "text", "text": "hi"}],
        status="complete",
    )
    with pytest.raises(IntegrityError):
        Message.objects.create(
            session=session,
            turn_index=0,
            role="assistant",
            content=[{"type": "text", "text": "hello"}],
            status="complete",
        )


def test_message_turn_index_can_repeat_across_sessions(user):
    s1 = Session.objects.create(owner=user, title="A")
    s2 = Session.objects.create(owner=user, title="B")
    Message.objects.create(
        session=s1,
        turn_index=0,
        role="user",
        sender_user=user,
        content=[{"type": "text", "text": "hi"}],
        status="complete",
    )
    # Should not raise
    Message.objects.create(
        session=s2,
        turn_index=0,
        role="user",
        sender_user=user,
        content=[{"type": "text", "text": "hi"}],
        status="complete",
    )


def test_only_one_open_next_draft_per_session(session, user):
    Draft.objects.create(
        session=session,
        creator_user=user,
        last_editor=user,
        slot="next",
        status="open",
        body="first",
    )
    with pytest.raises(IntegrityError):
        Draft.objects.create(
            session=session,
            creator_user=user,
            last_editor=user,
            slot="next",
            status="open",
            body="second",
        )


def test_can_have_multiple_queued_drafts(session, user):
    Draft.objects.create(
        session=session,
        creator_user=user,
        last_editor=user,
        slot="queued",
        queue_position=0,
        body="A",
    )
    Draft.objects.create(
        session=session,
        creator_user=user,
        last_editor=user,
        slot="queued",
        queue_position=1,
        body="B",
    )
    assert Draft.objects.filter(session=session, slot="queued").count() == 2


def test_sent_draft_does_not_block_new_next(session, user):
    """A draft with status='sent' should not block creating a new open 'next' draft."""
    Draft.objects.create(
        session=session,
        creator_user=user,
        last_editor=user,
        slot="next",
        status="sent",
        body="old",
    )
    # Should not raise — the partial unique index is on status='open'
    Draft.objects.create(
        session=session,
        creator_user=user,
        last_editor=user,
        slot="next",
        status="open",
        body="new",
    )


def test_share_token_is_auto_generated(session, user):
    token = ShareToken.objects.create(session=session, created_by=user)
    assert token.token
    assert len(token.token) >= 24


def test_ingest_upload_creates_audit_row(session, user):
    record = IngestUpload.objects.create(
        session=session,
        uploaded_by=user,
        source_path="/Users/jjackson/.claude/projects/-foo/abc.jsonl",
        raw_bytes=12345,
        line_count=42,
        cli_session_id="abc-123",
    )
    assert record.line_count == 42
```

- [ ] **Step 7: Run the model tests**

```bash
pytest apps/sessions/tests/test_models.py -v
```

Expected: all 9 tests pass. If `test_only_one_open_next_draft_per_session` fails, the partial unique index isn't supported by the test backend (SQLite supports it from 3.8+; verify your test SQLite is recent enough — `python -c "import sqlite3; print(sqlite3.sqlite_version)"`).

- [ ] **Step 8: Write `apps/sessions/admin.py`**

```python
from django.contrib import admin

from .models import Draft, IngestUpload, Message, Session, SessionParticipant, ShareToken


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("slug", "title", "owner", "backend_kind", "status", "source", "created_at")
    list_filter = ("backend_kind", "status", "source")
    search_fields = ("slug", "title", "owner__email")
    readonly_fields = ("slug", "created_at", "updated_at")


@admin.register(SessionParticipant)
class SessionParticipantAdmin(admin.ModelAdmin):
    list_display = ("session", "user", "role", "joined_at", "last_seen_at")
    list_filter = ("role",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("session", "turn_index", "role", "status", "started_at")
    list_filter = ("role", "status")
    readonly_fields = ("session", "turn_index", "role", "content", "plaintext")


@admin.register(Draft)
class DraftAdmin(admin.ModelAdmin):
    list_display = ("session", "slot", "queue_position", "status", "creator_user", "version")
    list_filter = ("slot", "status")


@admin.register(ShareToken)
class ShareTokenAdmin(admin.ModelAdmin):
    list_display = ("session", "token", "created_by", "revoked_at", "created_at")


@admin.register(IngestUpload)
class IngestUploadAdmin(admin.ModelAdmin):
    list_display = ("session", "uploaded_by", "line_count", "raw_bytes", "created_at")
```

- [ ] **Step 9: Run full suite**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add apps/sessions/
git commit -m "feat(sessions): add full data model with constraints and tests"
```

---

## Task 6: Wire Channels into ASGI (no consumers yet)

**Files:**
- Modify: `config/asgi.py` (already has the skeleton; just verify it loads)
- Create: `apps/sessions/routing.py` (empty for now, populated in Plan 1C)
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_asgi.py`

- [ ] **Step 1: Create empty routing module**

```python
# apps/sessions/routing.py
"""WebSocket routing for sessions. Populated in Plan 1C."""
from django.urls import re_path

websocket_urlpatterns: list = [
    # re_path(r"ws/session/(?P<slug>[\w-]+)/$", SessionConsumer.as_asgi()),
]
```

- [ ] **Step 2: Update `config/asgi.py` to import the routing module**

```python
"""ASGI entry point with Channels routing."""
import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

django_asgi_app = get_asgi_application()

from apps.sessions.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(URLRouter(websocket_urlpatterns)),
    }
)
```

- [ ] **Step 3: Create `tests/__init__.py` and `tests/conftest.py`**

```python
# tests/__init__.py
```

```python
# tests/conftest.py
"""Top-level pytest fixtures shared across all tests."""
```

- [ ] **Step 4: Write a smoke test that the ASGI app loads without errors**

```python
# tests/test_asgi.py
def test_asgi_application_loads():
    from config.asgi import application

    assert application is not None
```

- [ ] **Step 5: Run the test**

```bash
pytest tests/test_asgi.py -v
```

Expected: PASS.

- [ ] **Step 6: Smoke test the dev server with daphne (Channels-aware)**

```bash
DJANGO_SETTINGS_MODULE=config.settings.development daphne -b 127.0.0.1 -p 8001 config.asgi:application &
sleep 2
curl -s http://127.0.0.1:8001/api/health
kill %1
```

Expected: `{"data": {"status": "ok"}, "error": null}`

- [ ] **Step 7: Commit**

```bash
git add config/asgi.py apps/sessions/routing.py tests/
git commit -m "chore(channels): wire empty Channels routing into ASGI app"
```

---

## Task 7: React frontend skeleton

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/postcss.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/router.tsx`
- Create: `frontend/src/pages/HomePage.tsx`
- Create: `frontend/src/pages/HealthPage.tsx`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/styles/globals.css`

- [ ] **Step 1: Create the frontend directory and scaffold with Vite**

```bash
mkdir -p /Users/jjackson/emdash-projects/ace-web/frontend
cd /Users/jjackson/emdash-projects/ace-web/frontend
```

- [ ] **Step 2: Write `frontend/package.json`**

```json
{
  "name": "ace-web-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-router-dom": "^6.26.0"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.47",
    "tailwindcss": "^4.0.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0"
  }
}
```

- [ ] **Step 3: Write `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

- [ ] **Step 4: Write `frontend/vite.config.ts`**

```typescript
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    manifest: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true,
      },
    },
  },
})
```

- [ ] **Step 5: Write `frontend/tailwind.config.js`**

```javascript
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

- [ ] **Step 6: Write `frontend/postcss.config.js`**

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

- [ ] **Step 7: Write `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>ACE Web</title>
  </head>
  <body class="bg-gray-50 text-gray-900">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 8: Write `frontend/src/styles/globals.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 9: Write `frontend/src/main.tsx`**

```typescript
import React from "react"
import ReactDOM from "react-dom/client"
import App from "./App"
import "./styles/globals.css"

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

- [ ] **Step 10: Write `frontend/src/api/client.ts`**

```typescript
type Envelope<T> = { data: T | null; error: { code: string; message: string } | null }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  })
  const body = (await res.json()) as Envelope<T>
  if (body.error) {
    throw new Error(body.error.message)
  }
  return body.data as T
}

export const api = {
  health: () => request<{ status: string }>("/health"),
}
```

- [ ] **Step 11: Write `frontend/src/router.tsx`**

```typescript
import { createBrowserRouter, RouterProvider } from "react-router-dom"
import HomePage from "./pages/HomePage"
import HealthPage from "./pages/HealthPage"

const router = createBrowserRouter([
  { path: "/", element: <HomePage /> },
  { path: "/health-check", element: <HealthPage /> },
])

export function Router() {
  return <RouterProvider router={router} />
}
```

- [ ] **Step 12: Write `frontend/src/App.tsx`**

```typescript
import { Router } from "./router"

export default function App() {
  return <Router />
}
```

- [ ] **Step 13: Write `frontend/src/pages/HomePage.tsx`**

```typescript
import { Link } from "react-router-dom"

export default function HomePage() {
  return (
    <div className="mx-auto max-w-4xl p-12">
      <h1 className="text-3xl font-semibold">ACE Web Harness</h1>
      <p className="mt-4 text-gray-600">
        Foundation shell. Chat and transcripts arrive in Plan 1B.
      </p>
      <Link to="/health-check" className="mt-6 inline-block text-blue-600 underline">
        Check backend health
      </Link>
    </div>
  )
}
```

- [ ] **Step 14: Write `frontend/src/pages/HealthPage.tsx`**

```typescript
import { useEffect, useState } from "react"
import { api } from "../api/client"

export default function HealthPage() {
  const [status, setStatus] = useState<string>("loading...")
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .health()
      .then((r) => setStatus(r.status))
      .catch((e) => setError(String(e)))
  }, [])

  return (
    <div className="mx-auto max-w-4xl p-12">
      <h1 className="text-2xl font-semibold">Backend health</h1>
      {error ? (
        <p className="mt-4 text-red-600">Error: {error}</p>
      ) : (
        <p className="mt-4">Status: <span className="font-mono">{status}</span></p>
      )}
    </div>
  )
}
```

- [ ] **Step 15: Install frontend deps and build**

```bash
cd /Users/jjackson/emdash-projects/ace-web/frontend
npm install
npm run build
```

Expected: `frontend/dist/` directory created with hashed JS/CSS assets and an `index.html`.

- [ ] **Step 16: Verify Django can serve the built frontend**

```bash
cd /Users/jjackson/emdash-projects/ace-web
DJANGO_SETTINGS_MODULE=config.settings.development python manage.py collectstatic --noinput
DJANGO_SETTINGS_MODULE=config.settings.development python manage.py runserver 8000 &
sleep 2
curl -s http://localhost:8000/static/index.html | head -20
kill %1
```

Expected: HTML output with `<div id="root"></div>` visible.

- [ ] **Step 17: Commit**

```bash
cd /Users/jjackson/emdash-projects/ace-web
git add frontend/
git commit -m "feat(frontend): scaffold React + Vite + Tailwind shell with health page"
```

---

## Task 8: Dockerfile and entrypoint

**Files:**
- Create: `Dockerfile`
- Create: `entrypoint.sh`
- Create: `.env.example`

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1

# --- Stage 1: build the React frontend ---
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python runtime ---
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js so we can install the claude CLI later
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get update && apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install claude CLI globally
RUN npm install -g @anthropic-ai/claude

WORKDIR /app

# Python deps
COPY pyproject.toml ./
RUN pip install -e .

# Source
COPY manage.py ./
COPY config/ ./config/
COPY apps/ ./apps/

# Copy built frontend from stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Collect static assets
RUN python manage.py collectstatic --noinput

# Entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
```

- [ ] **Step 2: Write `entrypoint.sh`**

```bash
#!/bin/bash
set -e

# Bootstrap Claude CLI auth from Secret Manager if available.
# In Plan 1A this is a no-op; the actual token loading lands in Plan 1B
# when the CLIBackend is implemented.
if [ -n "${ACE_CLAUDE_TOKEN_SECRET}" ]; then
    echo "[entrypoint] Loading CLAUDE_CODE_OAUTH_TOKEN from secret ${ACE_CLAUDE_TOKEN_SECRET}"
    # Plan 1B: read from Secret Manager and write to ~/.claude/auth.json
fi

# Apply migrations
python manage.py migrate --noinput

# Start ASGI server
exec uvicorn config.asgi:application \
    --host 0.0.0.0 \
    --port "${PORT:-8080}" \
    --workers 1 \
    --lifespan off
```

- [ ] **Step 3: Write `.env.example`**

```bash
# Django
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DATABASE_URL=postgres://ace:ace@db:5432/ace_web

# Logging
ACE_LOG_LEVEL=INFO

# IAP (production only)
ACE_IAP_REQUIRED=False
ACE_IAP_DEV_FAKE_EMAIL=dev@example.com
ACE_IAP_DEV_FAKE_USER_ID=dev-user-1

# Claude (Plan 1B)
# ACE_CLAUDE_TOKEN_SECRET=projects/PROJECT_ID/secrets/claude-token/versions/latest
```

- [ ] **Step 4: Build the image locally**

```bash
cd /Users/jjackson/emdash-projects/ace-web
docker build -t ace-web:dev .
```

Expected: image builds successfully (will take a few minutes the first time due to npm + apt installs).

- [ ] **Step 5: Run the container against an ephemeral SQLite DB**

```bash
docker run --rm -p 8080:8080 \
  -e DJANGO_SETTINGS_MODULE=config.settings.development \
  -e DJANGO_DEBUG=True \
  -e DATABASE_URL=sqlite:///tmp/db.sqlite3 \
  ace-web:dev &
sleep 5
curl -s http://localhost:8080/api/health
docker stop $(docker ps -q --filter ancestor=ace-web:dev)
```

Expected: `{"data": {"status": "ok"}, "error": null}`. If the curl fails, check `docker logs` for the failing container.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile entrypoint.sh .env.example
git commit -m "chore(docker): add Dockerfile, entrypoint, and env template"
```

---

## Task 9: docker-compose for local dev with Postgres

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Write `docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: ace
      POSTGRES_PASSWORD: ace
      POSTGRES_DB: ace_web
    ports:
      - "5432:5432"
    volumes:
      - ace-pg-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ace"]
      interval: 5s
      timeout: 5s
      retries: 5

  app:
    build: .
    command: >
      bash -c "python manage.py migrate &&
               uvicorn config.asgi:application --host 0.0.0.0 --port 8080 --reload"
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.development
      DJANGO_DEBUG: "True"
      DJANGO_SECRET_KEY: dev-insecure
      DATABASE_URL: postgres://ace:ace@db:5432/ace_web
      ACE_IAP_REQUIRED: "False"
    ports:
      - "8000:8080"
    volumes:
      - ./apps:/app/apps
      - ./config:/app/config
      - ./manage.py:/app/manage.py
    depends_on:
      db:
        condition: service_healthy

volumes:
  ace-pg-data:
```

- [ ] **Step 2: Bring up the full stack**

```bash
cd /Users/jjackson/emdash-projects/ace-web
docker compose up --build -d
sleep 8
curl -s http://localhost:8000/api/health
```

Expected: `{"data": {"status": "ok"}, "error": null}`

- [ ] **Step 3: Verify migrations ran in the Postgres container**

```bash
docker compose exec db psql -U ace -d ace_web -c "\dt"
```

Expected: lists tables `users`, `sessions`, `session_participants`, `messages`, `drafts`, `share_tokens`, `ingest_uploads`, plus Django's built-in `auth_*`, `django_*`, `admin_*`.

- [ ] **Step 4: Bring the stack down**

```bash
docker compose down
```

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "chore(docker): add docker-compose for local dev with Postgres"
```

---

## Task 10: GCP Cloud Run deployment artifacts

**Files:**
- Create: `cloudbuild.yaml`
- Create: `docs/deploy.md`

- [ ] **Step 1: Write `cloudbuild.yaml`**

This is the Cloud Build config that builds the image and deploys it to Cloud Run. It assumes the GCP project is set up with Cloud SQL, IAP, and Secret Manager already configured (manual one-time setup documented in `docs/deploy.md`).

```yaml
steps:
  # Build the image
  - name: gcr.io/cloud-builders/docker
    args:
      - build
      - -t
      - ${_IMAGE_URI}
      - .

  # Push to Artifact Registry
  - name: gcr.io/cloud-builders/docker
    args:
      - push
      - ${_IMAGE_URI}

  # Deploy to Cloud Run
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    entrypoint: gcloud
    args:
      - run
      - deploy
      - ${_SERVICE_NAME}
      - --image=${_IMAGE_URI}
      - --region=${_REGION}
      - --platform=managed
      - --add-cloudsql-instances=${_CLOUD_SQL_CONNECTION_NAME}
      - --set-env-vars=DJANGO_SETTINGS_MODULE=config.settings.production
      - --set-env-vars=DJANGO_ALLOWED_HOSTS=${_ALLOWED_HOSTS}
      - --set-env-vars=CLOUD_SQL_CONNECTION_NAME=${_CLOUD_SQL_CONNECTION_NAME}
      - --set-env-vars=ACE_IAP_REQUIRED=True
      - --set-secrets=DJANGO_SECRET_KEY=django-secret:latest
      - --set-secrets=DATABASE_URL=database-url:latest
      - --min-instances=1
      - --max-instances=1
      - --memory=1Gi
      - --cpu=1
      - --no-allow-unauthenticated

substitutions:
  _SERVICE_NAME: ace-web
  _REGION: us-central1
  _IMAGE_URI: us-central1-docker.pkg.dev/${PROJECT_ID}/ace-web/app:${SHORT_SHA}
  _CLOUD_SQL_CONNECTION_NAME: ${PROJECT_ID}:us-central1:ace-web-db
  _ALLOWED_HOSTS: ace-web-xxxxx-uc.a.run.app

options:
  logging: CLOUD_LOGGING_ONLY
```

- [ ] **Step 2: Write `docs/deploy.md` with the one-time GCP setup steps**

```markdown
# Deploying ace-web to GCP Cloud Run

This document covers the one-time GCP project setup required before
`cloudbuild.yaml` will work. After this setup, every push to `main`
(once a Cloud Build trigger is configured) auto-deploys.

## Prerequisites

- A GCP project with billing enabled
- `gcloud` CLI installed and authenticated
- `PROJECT_ID` exported in your shell

## One-time setup

### 1. Enable required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  iap.googleapis.com
```

### 2. Create the Artifact Registry repo

```bash
gcloud artifacts repositories create ace-web \
  --repository-format=docker \
  --location=us-central1
```

### 3. Create the Cloud SQL instance

```bash
gcloud sql instances create ace-web-db \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=us-central1

gcloud sql databases create ace_web --instance=ace-web-db

gcloud sql users create ace --instance=ace-web-db --password='REPLACE_ME'
```

### 4. Store secrets

```bash
echo -n 'long-random-django-key' | \
  gcloud secrets create django-secret --data-file=-

echo -n 'postgres://ace:REPLACE_ME@/ace_web?host=/cloudsql/PROJECT_ID:us-central1:ace-web-db' | \
  gcloud secrets create database-url --data-file=-
```

### 5. Initial deploy

```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_ALLOWED_HOSTS=placeholder
```

After the first deploy, note the actual Cloud Run URL and update
`_ALLOWED_HOSTS` in `cloudbuild.yaml`.

### 6. Configure IAP

1. In the Cloud Console, navigate to **Security → Identity-Aware Proxy**
2. Find the `ace-web` Cloud Run service
3. Toggle IAP **on**
4. Add the team's Google accounts as **IAP-secured Web App User** principals

After IAP is configured, navigating to the service URL prompts a Google login.
Once logged in as an authorized user, requests reach the app with the
`X-Goog-Authenticated-User-Email` and `X-Goog-Authenticated-User-ID` headers
that the `IAPHeaderAuthMiddleware` reads.

## Smoke test

```bash
URL=$(gcloud run services describe ace-web --region=us-central1 --format='value(status.url)')
# Health check is publicly accessible (not behind IAP)
curl -s ${URL}/api/health
```

Expected: `{"data": {"status": "ok"}, "error": null}`

Then open `${URL}/` in a browser; you should see Google SSO and then the React shell.
```

- [ ] **Step 3: Commit**

```bash
git add cloudbuild.yaml docs/deploy.md
git commit -m "chore(deploy): add Cloud Build config and GCP setup docs"
```

---

## Task 11: First deploy and smoke test

**Files:** none new — this task is the manual GCP setup + deploy.

- [ ] **Step 1: Run through `docs/deploy.md` Steps 1-5**

You'll need to substitute your real `PROJECT_ID` and a real DB password. This is one-time setup.

- [ ] **Step 2: Trigger the first build**

```bash
cd /Users/jjackson/emdash-projects/ace-web
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_ALLOWED_HOSTS=placeholder.run.app
```

Expected: Cloud Build completes successfully and the `ace-web` Cloud Run service is created.

- [ ] **Step 3: Get the actual URL and update cloudbuild.yaml**

```bash
URL=$(gcloud run services describe ace-web --region=us-central1 --format='value(status.url)')
echo "${URL}"
# Strip https:// prefix to get the host for ALLOWED_HOSTS
HOST=${URL#https://}
echo "Update _ALLOWED_HOSTS in cloudbuild.yaml to: ${HOST}"
```

Edit `cloudbuild.yaml` and replace `_ALLOWED_HOSTS: ace-web-xxxxx-uc.a.run.app` with the real host.

- [ ] **Step 4: Redeploy with the correct ALLOWED_HOSTS**

```bash
gcloud builds submit --config=cloudbuild.yaml
```

- [ ] **Step 5: Verify the health check is reachable (it bypasses IAP)**

```bash
curl -s ${URL}/api/health
```

Expected: `{"data": {"status": "ok"}, "error": null}`

- [ ] **Step 6: Configure IAP and verify SSO works**

Follow `docs/deploy.md` Step 6. Then open `${URL}/` in a browser. You should see Google SSO, then the React `HomePage` after logging in.

- [ ] **Step 7: Verify the database is reachable from Cloud Run**

```bash
gcloud run services proxy ace-web --region=us-central1 &
sleep 3
curl -s -H "X-Goog-Authenticated-User-Email: accounts.google.com:you@example.com" \
       -H "X-Goog-Authenticated-User-Id: accounts.google.com:fake-id" \
       http://localhost:8080/admin/login/
kill %1
```

Expected: 200 (login page rendered) — confirms middleware ran and a User row was created in Cloud SQL.

- [ ] **Step 8: Commit any cloudbuild fixes**

```bash
git add cloudbuild.yaml
git commit -m "chore(deploy): pin allowed hosts to real Cloud Run URL"
```

- [ ] **Step 9: Tag the foundation milestone**

```bash
git tag -a v0.1.0-foundation -m "Plan 1A complete: deployable Django+Channels+React shell on GCP"
```

(Don't push the tag without explicit user approval per the safety protocol.)

---

## Self-review (engineer running this plan should also do this)

Before declaring Plan 1A done, verify:

- [ ] `pytest -v` passes locally with all tests green
- [ ] `docker compose up --build` brings the stack up cleanly and `curl localhost:8000/api/health` returns ok
- [ ] `psql` into the local Postgres shows all 7 tables (`users`, `sessions`, `session_participants`, `messages`, `drafts`, `share_tokens`, `ingest_uploads`)
- [ ] Cloud Run deploy succeeds and `${URL}/api/health` returns ok over HTTPS
- [ ] Browsing to `${URL}/` after Google SSO renders the React `HomePage`
- [ ] Cloud SQL has the same 7 tables (`gcloud sql connect ace-web-db --user=ace` then `\dt`)
- [ ] No `TODO` / `FIXME` / `placeholder` strings in any committed file (`grep -r "TODO\|FIXME\|placeholder"`)

If any of these fail, fix before moving to Plan 1B.

---

## What ships at the end of Plan 1A

- A real public-ish URL (Cloud Run + IAP) where the team can log in with Google and see a React page
- Postgres in Cloud SQL with the full ACE web data model migrated
- Health check endpoint
- IAP middleware that creates Django user rows on first sight
- Channels installed and ASGI configured (no consumers yet)
- Local dev via `docker compose up`
- Cloud Build config for one-shot redeploys

## What does NOT ship in Plan 1A (deferred to later plans)

- `ChatBackend` interface or any backend implementation → **Plan 1B**
- REST API for sessions/messages → **Plan 1B**
- Any chat UI → **Plan 1B**
- WebSocket consumer for sessions → **Plan 1C**
- Draft collaboration model → **Plan 1C**
- Presence indicators → **Plan 1C**
- Session list page, share tokens, `ace upload` CLI → **Plan 1D**
- Claude CLI auth flow (PTY-based `claude setup-token`) → **Plan 1B** (when CLIBackend lands)

---

## Post-execution corrections

Issues found during review of the executed plan that a future re-runner should apply on top of the tasks above. Each has a corresponding fix-up commit in the `ace-web` repo for cross-reference.

### Task 2 — Django project skeleton

**Security (3 issues, commit `150421f`):**

1. `config/settings/base.py`: `ALLOWED_HOSTS` default should be `[]`, not `["*"]`. The wildcard fallback in base is dangerous because it flows to production if `production.py` misconfigures. Development.py overrides to `["*"]` so dev is unaffected.
2. `config/settings/base.py`: guard the `.env` read with `if (BASE_DIR / ".env").exists():` — unconditional read is surprising in Cloud Run where there is no `.env` file, and can mask config errors.
3. `config/settings/production.py`: add `SECRET_KEY = env("DJANGO_SECRET_KEY")` with NO default, so a misconfigured prod deploy crashes at startup instead of silently using the dev key.
4. `config/settings/production.py`: add a prominent WARNING comment that `CHANNEL_LAYERS` is still `InMemoryChannelLayer` from base.py and must be replaced with `channels-redis` before scaling Cloud Run past `max-instances=1` (Plan 1C).
5. Add explanatory comments to `config/asgi.py` and `config/wsgi.py` about why they default `DJANGO_SETTINGS_MODULE` to production.
6. Add a forward-reference comment in `config/urls.py` noting that `apps.common.urls` is created in Task 3 (transient broken state between Tasks 2 and 3).

### Task 3 — Common app + health

**Test environment (commit `ef368e1`):**

7. `config/settings/test.py` must filter forward-referenced apps/middleware while Tasks 4 and 5 are still pending. Add:

```python
_unbuilt_apps = {"apps.auth.apps.AuthConfig", "apps.sessions.apps.SessionsConfig"}
_unbuilt_middleware = {"apps.auth.middleware.IAPHeaderAuthMiddleware"}
INSTALLED_APPS = [a for a in INSTALLED_APPS if a not in _unbuilt_apps]
MIDDLEWARE = [m for m in MIDDLEWARE if m not in _unbuilt_middleware]
AUTH_USER_MODEL = "auth.User"  # base.py points to ace_auth.User which doesn't exist yet
```

Each subsequent task removes its entries from the filter sets. By Task 5 the sets are empty and the override block should be deleted entirely (see Issue 14).

### Task 4 — Auth app and IAP middleware

**Data integrity and races (commit `dbcc37f`):**

8. `apps/auth/managers.py`: `create_user` must default `google_sub=None` (not `""`) and coerce falsy to `None` via `google_sub or None`. Empty string would collide on the UNIQUE constraint the second time a user is created without a sub.
9. `apps/auth/middleware.py`: `_get_or_create_user` must handle `IntegrityError` on the create path and re-fetch — otherwise concurrent first-logins for the same email will 500.
10. Add `test_two_users_without_google_sub_can_coexist`, `test_existing_user_is_returned_not_recreated`, and `test_google_sub_is_backfilled_when_missing` to cover the scenarios above.
11. Add a NOTE comment inside `IAPHeaderAuthMiddleware` that it only runs on HTTP requests — Plan 1C must add equivalent auth handling for WebSocket ASGI scopes.

### Task 5 — Sessions data model

**Schema and polish (commit `065b503`):**

12. `apps/sessions/models.py`: `Message.started_at` must NOT be `auto_now_add=True`. It should be `models.DateTimeField(null=True, blank=True)` so the consumer can set it explicitly when streaming begins. With `auto_now_add=True` it always equals `created_at` and is useless.
13. `apps/sessions/models.py`: add a `save()` override on `Session` that retries with a fresh slug on `IntegrityError` — 48 bits of entropy is plenty but the failure mode is a confusing error.
14. `apps/sessions/models.py`: remove the redundant explicit `models.Index(fields=["session", "turn_index"])` from `Message.Meta.indexes` — the `UniqueConstraint` on the same fields already creates the index.
15. `apps/sessions/tests/test_models.py`: remove any developer-specific hardcoded paths (e.g., `/Users/jjackson/...`) and use `/tmp/...` instead.

### Whole-plan review corrections (commits `a091bad` + `30d54ff`)

After all tasks completed, a final whole-plan review caught cross-cutting issues:

16. **Critical:** `config/urls.py` had no SPA catch-all — navigating to `/` or any React Router route returned 404. Add a `TemplateView` catch-all for non-api/non-admin/non-static paths:

```python
re_path(
    r"^(?!api/|admin/|static/).*$",
    TemplateView.as_view(template_name="index.html"),
    name="spa",
),
```

17. **Critical:** `docker-compose.yml` `command:` key is silently ignored because Dockerfile uses `ENTRYPOINT` with no `CMD`. Either make `entrypoint.sh` conditionally pass `--reload` when `DJANGO_DEBUG=True` (the chosen fix) or have entrypoint.sh use `exec "$@"`. Local dev hot-reload was silently broken before this fix.

18. **Important:** Remove Node.js and `@anthropic-ai/claude-code` installation from the production Dockerfile — Plan 1A does not use the CLI. Plan 1B will add them via a separate stage when the CLIBackend ships. Having them in 1A bloats the image by ~200 MB and expands attack surface for no benefit.

19. **Important:** `docs/deploy.md` smoke test `curl /api/health` would return 403 because `--no-allow-unauthenticated` routes all traffic through IAP first. Update to:

```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" ${URL}/api/health
```

20. **Important:** Add `tests/`, `apps/*/tests/`, `conftest.py` to `.dockerignore` so test files don't ship in the production image.

21. **Important:** Remove unused `pydantic` and `daphne` from `pyproject.toml` dependencies — neither is imported anywhere.

22. **Minor:** After Task 5 completes, `config/settings/test.py` should lose the `_unbuilt_apps`/`_unbuilt_middleware` filter machinery (now dead code since all apps are built).

23. **Minor:** `config/settings/production.py`: `ALLOWED_HOSTS` default should be removed entirely. `env.list("DJANGO_ALLOWED_HOSTS")` with no fallback means a misconfigured deploy crashes at startup.

24. **Minor:** Add security headers to `production.py`:

```python
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
```

25. **Cross-cutting:** The `Dockerfile` `collectstatic` build step needs `DJANGO_ALLOWED_HOSTS=build-time-placeholder` inline (alongside the existing `DJANGO_SECRET_KEY=build-time-placeholder`) once fix #23 removes the default. Inline on the same `RUN` line so it does not leak into the runtime image.

### Known pre-existing follow-ups (not blocking)

- **Setuptools flat-layout discovery:** `pip install -e .` fails because the repo has `apps/`, `config/`, `frontend/`, and `staticfiles/` at the top level and setuptools can't guess which is the package. Add `[tool.setuptools.packages.find]` configuration with `include = ["apps*", "config*"]` to `pyproject.toml`. Tests pass because the venv was installed earlier with a working set of packages; this bites a future fresh install.
- **Slug retry test coverage:** The `Session.save()` collision retry loop has no test. Add one using `unittest.mock.patch` on `generate_slug`. Low priority — the collision probability is essentially zero.

### Final commits in order

```
05ceb29 chore: initialize ace-web repo with Django stack                    (Task 1)
57c863e chore: scaffold Django project with split settings and ASGI          (Task 2)
150421f fix(settings): tighten production defaults per code review           (fixes 1-6)
36ec017 feat(common): add health check endpoint with envelope wrapper        (Task 3)
ef368e1 fix(tests): filter forward-referenced apps from test settings        (fix 7)
184cd8e feat(auth): add custom User model and IAP header middleware          (Task 4)
dbcc37f fix(auth): coerce empty google_sub to NULL and handle race           (fixes 8-11)
8c61c76 feat(sessions): add full data model with constraints and tests       (Task 5)
065b503 fix(sessions): clean up Message timestamps, slug retries, polish     (fixes 12-15)
e0290a6 chore(channels): wire empty Channels routing into ASGI app           (Task 6)
deeda31 feat(frontend): scaffold React + Vite + Tailwind shell               (Task 7)
2c9ddb1 chore(docker): add Dockerfile, entrypoint, and env template          (Task 8)
767ff5e chore(docker): add docker-compose for local dev + dockerignore       (Task 9)
8272178 chore(deploy): add Cloud Build config and GCP setup docs             (Task 10)
a091bad fix(1a): address whole-plan review findings                          (fixes 16-24)
30d54ff fix(1a): pass DJANGO_ALLOWED_HOSTS placeholder during collectstatic  (fix 25)
```

Plan 1B should start from `30d54ff` or later.
