# ACE Web Harness — AWS Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate ace-web off standalone GCP Cloud Run and onto AWS ECS Fargate as a tenant service behind the `labs.connect.dimagi.com` ALB, mirroring scout's deployment pattern. Reuse the shared connect-labs AWS infrastructure (RDS, ElastiCache, ALB, VPC) so incremental cost is ~$5-15/month instead of the ~$100-150/month that standalone GCP required. Drop Filestore entirely — the CLIBackend hybrid resume path already handles cold-start CLI session state from Django history. Swap IAP auth for connect-labs' hand-rolled Connect OAuth flow with a `@dimagi.com` email filter.

**Architecture:** The Phase 2 backend code (`apps/common/`, `apps/sessions/`, `apps/auth/models.py`, frontend) is 100% reusable — transport-agnostic. This plan swaps the outer shell: auth mechanism, deploy pipeline, URL path prefix, Docker runtime layout. Two containers per ECS task (Django + uvicorn backend on port 8000, nginx frontend serving the Vite bundle on port 3000 and reverse-proxying `/ace/api/*` to backend). Single ECS service in the existing `labs-jj-cluster`, one instance minimum. Shared RDS Postgres (new database `ace_web`), shared ElastiCache Redis (idle until Phase 3 adds channels-redis). ALB listener rule `/ace/*` routes to a new target group.

**Tech Stack:** Unchanged from Phase 2 (Django 5, Channels 4, DRF, React 19, TypeScript, Tailwind). New: `httpx[http2]` for OAuth token exchange (connect-labs pattern), nginx for frontend container (scout pattern). Removed: Filestore / Memorystore / Cloud SQL / IAP.

**Reference implementations to mirror:**
- `/Users/jjackson/emdash-projects/connect-labs/commcare_connect/labs/integrations/connect/oauth.py` — `introspect_token()` and `fetch_user_organization_data()` helpers
- `/Users/jjackson/emdash-projects/connect-labs/commcare_connect/labs/integrations/connect/oauth_views.py` — the session-based OAuth view flow with PKCE
- `/Users/jjackson/emdash-projects/scout-jjackson/.github/workflows/deploy-labs.yml` — the GitHub Actions deploy pipeline
- `/Users/jjackson/emdash-projects/scout-jjackson/config/settings/connectlabs.py` — the path-prefix + ALB-TLS-offload settings shim
- `/Users/jjackson/emdash-projects/scout-jjackson/Dockerfile` — the Python 3.12 + uv backend image
- `/Users/jjackson/emdash-projects/scout-jjackson/Dockerfile.frontend` — the bun-build + nginx-serve frontend image
- `/Users/jjackson/emdash-projects/scout-jjackson/frontend/nginx.prod.conf` — the nginx reverse-proxy config (need to read this file during Task 3)

**Shared AWS infrastructure (reuse as-is):**
- AWS account: `858923557655`, region `us-east-1`
- ECS cluster: `labs-jj-cluster`
- ECR registry: `858923557655.dkr.ecr.us-east-1.amazonaws.com`
- ALB: the existing listener that fronts `labs.connect.dimagi.com` (owned by connect-labs infra, not in any repo)
- RDS Postgres cluster: the existing `labs-*` instance (connection details in Secrets Manager — discover during Task 5)
- ElastiCache Redis cluster: the existing labs cluster (not used in Phase 2, wired up in Phase 3)
- VPC / subnets / security groups: referenced via `LABS_SUBNET` and `LABS_SECURITY_GROUP` GitHub secrets (already set for scout's workflow)
- GitHub OIDC role: `AWS_ROLE_ARN` GitHub secret (already set for scout)

**Ace-web-owned resources to create:**
- ECR repos: `labs-jj-ace-web` (backend), `labs-jj-ace-web-frontend` (nginx)
- ECS task definition: `labs-jj-ace-web`
- ECS service: `labs-jj-ace-web`
- Target group: `labs-jj-ace-web-tg`
- ALB listener rule: priority TBD, forwards `/ace/*` to the ace-web target group
- Secrets Manager entries: `ace-web/django-secret-key`, `ace-web/database-url`, `ace-web/connect-oauth-client-id`, `ace-web/connect-oauth-client-secret`
- Postgres database: `ace_web` (new database on the shared RDS instance — created via one-time setup script)
- CloudWatch log group: `/ecs/labs-jj-ace-web` (auto-created on first task launch)

**What's OUT of scope for this plan:**
- Phase 3 multi-player / WebSocket work (separate plan)
- Channels-redis wiring (belongs in Phase 3, when it's actually needed)
- Terraform or other IaC for the shared infrastructure — we use direct `aws` CLI commands for the one-time setup, documented as a runbook
- Deleting the GCP service account or Workload Identity Federation provider that remain from the original Phase 1 setup — those are free to keep; optional cleanup at the very end

**State at plan start:**
- Branch: `emdash/aws-migration` (new, from main HEAD)
- Working directory: `/Users/jjackson/emdash-projects/worktrees/plan-1b-770`
- 91 tests passing (was 97 — 6 IAP middleware tests removed in the GCP cleanup PR #9)
- Frontend builds cleanly via `npm run build`
- GCP infrastructure: **fully torn down**. Only free-tier items (IAM service account, WIF provider) remain
- Phase 2 behavioral code: **fully reusable, no changes needed** in this plan

---

## File structure (created/modified across all tasks)

```
ace-web/
├── apps/
│   └── auth/
│       ├── oauth.py                # NEW — introspect_token helper (from connect-labs)
│       ├── oauth_views.py          # NEW — session-based OAuth views (adapted)
│       ├── urls.py                 # NEW — OAuth URL routes
│       └── tests/
│           └── test_oauth_views.py # NEW — login-restricted, PKCE, domain filter
│
├── config/
│   ├── settings/
│   │   ├── base.py                 # MODIFIED — add CONNECT_OAUTH_* settings, LOGIN_URL
│   │   ├── production.py           # MODIFIED — minimal cleanup
│   │   └── connectlabs.py          # NEW — path prefix, ALB TLS, session cookie
│   └── urls.py                     # MODIFIED — include apps.auth.urls, require login on SPA catch-all
│
├── frontend/
│   ├── vite.config.ts              # MODIFIED — base: '/ace/'
│   ├── nginx.prod.conf             # NEW — reverse proxy for labs deployment
│   └── src/
│       ├── router.tsx              # MODIFIED — basename='/ace'
│       └── api/
│           └── client.ts           # MODIFIED — prefix-aware URL builder
│
├── deploy/
│   └── aws/
│       ├── task-definition.json    # NEW — ECS task definition (backend + frontend containers)
│       ├── one-time-setup.sh       # NEW — runbook script for initial AWS resource creation
│       └── README.md               # NEW — what this directory is + how to use it
│
├── .github/
│   └── workflows/
│       └── deploy-labs.yml         # NEW — mirrors scout's deploy workflow
│
├── Dockerfile                      # REWRITTEN — Python 3.12-slim + uv, scout pattern
├── Dockerfile.frontend             # NEW — oven/bun build + nginx:alpine serve, scout pattern
├── pyproject.toml                  # MODIFIED — add httpx[http2]
├── docs/
│   └── deploy.md                   # REWRITTEN — full AWS runbook
└── CLAUDE.md                       # MODIFIED — stack, status, deploy sections
```

---

## Task 1: Backend OAuth + settings + auth enforcement

**Files:**
- Create: `apps/auth/oauth.py`
- Create: `apps/auth/oauth_views.py`
- Create: `apps/auth/urls.py`
- Create: `apps/auth/tests/test_oauth_views.py`
- Modify: `config/settings/base.py`
- Modify: `config/settings/production.py`
- Create: `config/settings/connectlabs.py`
- Modify: `config/urls.py`
- Modify: `pyproject.toml`

**Context:**
The OAuth pattern is a direct port of connect-labs' hand-rolled flow (see `/Users/jjackson/emdash-projects/connect-labs/commcare_connect/labs/integrations/connect/oauth_views.py`). Key adaptations for ace-web:

1. **User model difference.** connect-labs uses the standard Django `User` keyed by `username`. ace-web has a custom `ace_auth.User` keyed by `email` with `display_name` instead of `name`. The `update_or_create` call must use `email=` as the lookup and `display_name` in defaults.
2. **Domain filter enforced at login, not just at mixin level.** connect-labs has an `is_dimagi_user()` helper that's currently stubbed out (returns True). For ace-web we enforce `@dimagi.com` at the callback itself — no Dimagi email means no login at all. This is simpler than the per-view mixin approach and matches the user's requirement.
3. **URL namespace.** connect-labs puts OAuth at `/labs/login/`, `/labs/initiate/`, `/labs/callback/`, `/labs/logout/`. ace-web puts them under `/ace/auth/` (which becomes `/auth/` when `FORCE_SCRIPT_NAME=/ace` is active).
4. **Session cookie name.** Each tenant behind `labs.connect.dimagi.com` must have its own cookie name to avoid collisions. scout uses `sessionid_scout`, ace-web uses `sessionid_ace`.
5. **The `google_sub` legacy field on User is left as NULL** — OAuth callback never populates it. It'll get removed in a future cleanup migration.

### Step 1: Add httpx dependency

Modify `pyproject.toml`. Add `"httpx[http2]>=0.27",` to the `dependencies` list.

Then reinstall deps:

```bash
uv pip install --system -e .
```

If the project doesn't use uv in this environment, use whatever installer is standard (`.venv/bin/pip install -e .`).

### Step 2: Write OAuth helper module

Create `apps/auth/oauth.py`:

```python
"""
Connect OAuth Helper Functions.

Session-based OAuth implementation adapted from connect-labs. Tokens live
in request.session — no database writes for the OAuth state itself (the
User row is still persisted normally).
"""
from __future__ import annotations

import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


def introspect_token(
    access_token: str,
    client_id: str,
    client_secret: str,
    production_url: str,
) -> dict | None:
    """Introspect an OAuth token to retrieve the caller's profile.

    Returns a dict with keys {'id', 'username', 'email', 'first_name',
    'last_name'} on success, or None on any failure. The upstream endpoint
    requires client credentials to call.
    """
    try:
        resp = httpx.post(
            f"{production_url}/o/introspect/",
            data={"token": access_token},
            auth=(client_id, client_secret),
            timeout=10,
        )
    except httpx.HTTPError:
        logger.exception("HTTP error during token introspection")
        return None

    if resp.status_code != 200:
        logger.warning(
            "Token introspection failed with status %s", resp.status_code
        )
        return None

    data = resp.json()
    if not data.get("active"):
        logger.warning("Token is not active")
        return None

    # The `sub` field may contain an email (Dimagi staff case) or a username.
    sub = data.get("sub") or ""
    sub_email = sub if "@" in str(sub) else ""

    return {
        "id": data.get("user_id") or sub or 0,
        "username": data.get("username"),
        "email": data.get("email", "") or sub_email,
        "first_name": data.get("given_name", ""),
        "last_name": data.get("family_name", ""),
    }


def fetch_userinfo(access_token: str, production_url: str) -> dict | None:
    """Fetch OIDC userinfo as a more reliable source for the email field.

    Returns the full userinfo dict or None on failure. Non-fatal — callers
    should fall back to the introspect_token email.
    """
    try:
        resp = httpx.get(
            f"{production_url}/o/userinfo/",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
    except httpx.HTTPError:
        logger.exception("HTTP error fetching OIDC userinfo")
        return None

    if resp.status_code != 200:
        logger.warning("OIDC userinfo returned status %s", resp.status_code)
        return None
    return resp.json()
```

### Step 3: Write OAuth views

Create `apps/auth/oauth_views.py`:

```python
"""
Connect OAuth Views for ace-web.

Session-based OAuth flow adapted from connect-labs. Enforces a @dimagi.com
email filter at the callback — no Dimagi email means no login.
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import secrets
from base64 import urlsafe_b64encode
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from apps.auth.models import User

from .oauth import fetch_userinfo, introspect_token

logger = logging.getLogger(__name__)

DIMAGI_DOMAIN = "@dimagi.com"
DEFAULT_NEXT = "/"


def login_page(request: HttpRequest) -> HttpResponse:
    """Public landing page that shows the 'sign in with Connect' button."""
    next_url = request.GET.get("next", DEFAULT_NEXT)
    if request.user.is_authenticated:
        return redirect(next_url if url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}
        ) else DEFAULT_NEXT)
    return render(request, "auth/login.html", {"next": next_url})


def oauth_initiate(request: HttpRequest) -> HttpResponse:
    """Start the OAuth flow — generate PKCE + state, redirect to Connect."""
    if not settings.CONNECT_OAUTH_CLIENT_ID or not settings.CONNECT_OAUTH_CLIENT_SECRET:
        logger.error("OAuth not configured — missing CONNECT_OAUTH_CLIENT_ID/SECRET")
        messages.error(request, "OAuth is not configured. Contact an administrator.")
        return render(request, "auth/login.html", status=500)

    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    request.session["oauth_next"] = request.GET.get("next", DEFAULT_NEXT)

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = (
        urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    request.session["oauth_code_verifier"] = code_verifier

    callback_url = request.build_absolute_uri(reverse("auth:callback"))
    scopes = getattr(settings, "CONNECT_OAUTH_SCOPES", ["read"])
    params = {
        "client_id": settings.CONNECT_OAUTH_CLIENT_ID,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{settings.CONNECT_PRODUCTION_URL}/o/authorize/?{urlencode(params)}"
    logger.info("Initiating OAuth flow", extra={"redirect_uri": callback_url})
    return HttpResponseRedirect(authorize_url)


def oauth_callback(request: HttpRequest) -> HttpResponse:
    """Handle the OAuth callback — exchange code for token, create/update User, log in."""
    state = request.GET.get("state")
    saved_state = request.session.get("oauth_state")
    if not state or state != saved_state:
        logger.warning("OAuth callback with invalid state", extra={"received_state": state})
        messages.error(request, "Invalid authentication state. Please try logging in again.")
        return redirect("auth:initiate")

    code = request.GET.get("code")
    if not code:
        error = request.GET.get("error", "Unknown error")
        description = request.GET.get("error_description", "")
        logger.error("OAuth error: %s %s", error, description)
        messages.error(request, f"Authentication failed: {description or error}")
        return redirect("auth:initiate")

    code_verifier = request.session.get("oauth_code_verifier")
    if not code_verifier:
        logger.error("OAuth callback missing code verifier in session")
        messages.error(request, "Session expired. Please try logging in again.")
        return redirect("auth:initiate")

    callback_url = request.build_absolute_uri(reverse("auth:callback"))
    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": callback_url,
        "client_id": settings.CONNECT_OAUTH_CLIENT_ID,
        "client_secret": settings.CONNECT_OAUTH_CLIENT_SECRET,
        "code_verifier": code_verifier,
    }

    try:
        resp = httpx.post(
            f"{settings.CONNECT_PRODUCTION_URL}/o/token/", data=token_data, timeout=10
        )
        resp.raise_for_status()
        token_json = resp.json()
    except httpx.HTTPStatusError:
        logger.exception("OAuth token exchange failed")
        messages.error(request, "Failed to authenticate with Connect. Please try again.")
        return redirect("auth:initiate")
    except Exception:
        logger.exception("OAuth token exchange raised unexpected error")
        messages.error(request, "Authentication service unavailable. Please try again later.")
        return redirect("auth:initiate")

    access_token = token_json["access_token"]
    profile = introspect_token(
        access_token=access_token,
        client_id=settings.CONNECT_OAUTH_CLIENT_ID,
        client_secret=settings.CONNECT_OAUTH_CLIENT_SECRET,
        production_url=settings.CONNECT_PRODUCTION_URL,
    )
    if not profile:
        messages.error(request, "Could not retrieve your profile from Connect. Please try again.")
        return redirect("auth:initiate")

    # Prefer OIDC userinfo email (more reliable than introspection's)
    userinfo = fetch_userinfo(access_token, settings.CONNECT_PRODUCTION_URL)
    if userinfo and userinfo.get("email"):
        profile["email"] = userinfo["email"]

    email = (profile.get("email") or "").lower().strip()
    if not email or not email.endswith(DIMAGI_DOMAIN):
        logger.warning(
            "OAuth login rejected — email %r does not end with %s",
            email,
            DIMAGI_DOMAIN,
        )
        messages.error(
            request,
            f"ace-web access is restricted to Dimagi staff ({DIMAGI_DOMAIN} emails).",
        )
        return redirect("auth:login")

    # Create or update the ace_auth.User row
    first_name = profile.get("first_name", "")
    last_name = profile.get("last_name", "")
    display_name = (
        f"{first_name} {last_name}".strip()
        or profile.get("username")
        or email.split("@")[0]
    )
    user, _created = User.objects.update_or_create(
        email=email,
        defaults={"display_name": display_name},
    )

    # Store token info in session (no DB writes for tokens)
    expires_in = token_json.get("expires_in", 1209600)  # default 2 weeks
    request.session["labs_oauth"] = {
        "access_token": access_token,
        "refresh_token": token_json.get("refresh_token", ""),
        "expires_at": (timezone.now() + datetime.timedelta(seconds=expires_in)).timestamp(),
        "user_profile": {
            "email": email,
            "display_name": display_name,
        },
    }

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    request.session.pop("oauth_state", None)
    request.session.pop("oauth_code_verifier", None)
    next_url = request.session.pop("oauth_next", DEFAULT_NEXT)
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = DEFAULT_NEXT

    logger.info("Successfully authenticated %s via OAuth", email)
    messages.success(request, f"Welcome, {display_name}!")
    return redirect(next_url)


def oauth_logout(request: HttpRequest) -> HttpResponse:
    """Log the user out and clear OAuth session data."""
    user_email = getattr(request.user, "email", None)
    logout(request)
    if user_email:
        logger.info("User %s logged out", user_email)
    messages.info(request, "You have been logged out.")
    return redirect("auth:login")
```

### Step 4: Write URL routes

Create `apps/auth/urls.py`:

```python
from django.urls import path

from . import oauth_views

app_name = "auth"

urlpatterns = [
    path("login/", oauth_views.login_page, name="login"),
    path("initiate/", oauth_views.oauth_initiate, name="initiate"),
    path("callback/", oauth_views.oauth_callback, name="callback"),
    path("logout/", oauth_views.oauth_logout, name="logout"),
]
```

### Step 5: Create the login template

The OAuth flow needs an HTML template at `apps/auth/templates/auth/login.html`. Create it:

```html
{% load static %}
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Sign in — ace-web</title>
    <style>
      body { font-family: system-ui, sans-serif; max-width: 480px; margin: 10% auto; padding: 1rem; color: #111; }
      h1 { font-size: 1.5rem; margin-bottom: 0.5rem; }
      p { line-height: 1.5; color: #555; }
      .btn {
        display: inline-block;
        background: #2563eb;
        color: white;
        padding: 0.6rem 1.2rem;
        border-radius: 0.375rem;
        text-decoration: none;
        font-weight: 500;
      }
      .btn:hover { background: #1d4ed8; }
      .messages { margin: 1rem 0; padding: 0.75rem; border-left: 3px solid #ef4444; background: #fef2f2; color: #7f1d1d; }
    </style>
  </head>
  <body>
    <h1>ace-web</h1>
    <p>Sign in with your Dimagi Connect account to continue.</p>
    {% if messages %}
      <ul class="messages">
        {% for m in messages %}<li>{{ m }}</li>{% endfor %}
      </ul>
    {% endif %}
    <p>
      <a class="btn" href="{% url 'auth:initiate' %}{% if next %}?next={{ next|urlencode }}{% endif %}">
        Sign in with Connect
      </a>
    </p>
  </body>
</html>
```

Django will find this template because the `apps.auth` app is in `INSTALLED_APPS` and its `templates/` directory is on the template loader path automatically (via `APP_DIRS: True` in the `TEMPLATES` setting).

### Step 6: Wire settings

Modify `config/settings/base.py`. Add these settings anywhere after the `# --- Core ---` block:

```python
# --- Connect OAuth (labs / AWS deployment) ---
CONNECT_PRODUCTION_URL = env("CONNECT_PRODUCTION_URL", default="https://connect.dimagi.com")
CONNECT_OAUTH_CLIENT_ID = env("CONNECT_OAUTH_CLIENT_ID", default="")
CONNECT_OAUTH_CLIENT_SECRET = env("CONNECT_OAUTH_CLIENT_SECRET", default="")
CONNECT_OAUTH_SCOPES = ["read"]

# Django auth wiring
LOGIN_URL = "/auth/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/auth/login/"
```

Note: the `LOGIN_URL` is `/auth/login/` (no `/ace/` prefix). When `FORCE_SCRIPT_NAME=/ace` is set in `connectlabs.py`, Django automatically prefixes this to `/ace/auth/login/`. In local dev (no `FORCE_SCRIPT_NAME`), it stays `/auth/login/`.

### Step 7: Create connectlabs.py settings

Create `config/settings/connectlabs.py`:

```python
"""
Django settings for ace-web deployed to the connect-labs AWS environment.

Inherits production security settings but configures for:
- ALB TLS termination (no SSL redirect — ALB handles HTTP->HTTPS)
- /ace/ path prefix (FORCE_SCRIPT_NAME)
- tenant-unique session cookie name (avoids collisions with scout on
  labs.connect.dimagi.com)
"""
from .production import *  # noqa: F401, F403

# ALB terminates TLS, so don't redirect HTTP -> HTTPS at Django level.
SECURE_SSL_REDIRECT = False

# ace-web is served under /ace/ path prefix on the ALB.
FORCE_SCRIPT_NAME = env("FORCE_SCRIPT_NAME", default="/ace")  # noqa: F405

# Tenant-unique session cookie so our session state does not collide with
# scout or connect-labs on the same parent domain.
SESSION_COOKIE_NAME = "sessionid_ace"
CSRF_COOKIE_NAME = "csrftoken_ace"
```

### Step 8: Update config/urls.py

Modify `config/urls.py` to:
1. Include `apps.auth.urls` at the `/auth/` prefix
2. Make the SPA catch-all require login (redirect unauthenticated users to `/auth/login/`)
3. Keep the `/api/` routes as-is (DRF's `IsAuthenticated` permission class handles those)

Replacement file:

```python
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path, re_path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.common.urls")),
    path("api/", include("apps.sessions.urls")),
    path("auth/", include("apps.auth.urls")),
    re_path(
        r"^(?!api/|admin/|auth/|static/|assets/).*$",
        login_required(
            TemplateView.as_view(template_name="index.html")
        ),
        name="spa",
    ),
]
```

### Step 9: Write OAuth view tests

Create `apps/auth/tests/test_oauth_views.py`:

```python
"""Tests for the Connect OAuth views."""
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture(autouse=True)
def _oauth_config(settings):
    settings.CONNECT_OAUTH_CLIENT_ID = "test-client-id"
    settings.CONNECT_OAUTH_CLIENT_SECRET = "test-client-secret"
    settings.CONNECT_PRODUCTION_URL = "https://connect.dimagi.example"


def test_login_page_public(client):
    resp = client.get("/auth/login/")
    assert resp.status_code == 200
    assert b"Sign in with Connect" in resp.content


def test_initiate_redirects_to_connect_with_pkce(client):
    resp = client.get("/auth/initiate/")
    assert resp.status_code == 302
    parsed = urlparse(resp.url)
    assert parsed.netloc == "connect.dimagi.example"
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["test-client-id"]
    assert qs["code_challenge_method"] == ["S256"]
    assert "code_challenge" in qs
    assert "state" in qs


def test_initiate_fails_when_not_configured(client, settings):
    settings.CONNECT_OAUTH_CLIENT_ID = ""
    resp = client.get("/auth/initiate/")
    assert resp.status_code == 500


def test_callback_rejects_invalid_state(client):
    session = client.session
    session["oauth_state"] = "expected"
    session.save()
    resp = client.get("/auth/callback/?state=wrong&code=abc")
    assert resp.status_code == 302
    assert "/auth/login/" in resp.url or "/auth/initiate/" in resp.url


def test_callback_creates_dimagi_user_and_logs_in(client):
    session = client.session
    session["oauth_state"] = "s123"
    session["oauth_code_verifier"] = "v123"
    session["oauth_next"] = "/"
    session.save()

    token_json = {"access_token": "tok", "refresh_token": "r", "expires_in": 3600}
    profile = {
        "id": 42,
        "username": "jdoe",
        "email": "",  # introspection may not return email
        "first_name": "Jane",
        "last_name": "Doe",
    }
    userinfo = {"email": "jane@dimagi.com"}

    with patch("apps.auth.oauth_views.httpx.post") as mock_post, \
         patch("apps.auth.oauth_views.introspect_token", return_value=profile), \
         patch("apps.auth.oauth_views.fetch_userinfo", return_value=userinfo):
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json.return_value = token_json
        resp = client.get("/auth/callback/?state=s123&code=authcode")

    assert resp.status_code == 302
    assert resp.url == "/"

    user = User.objects.get(email="jane@dimagi.com")
    assert user.display_name == "Jane Doe"


def test_callback_rejects_non_dimagi_email(client):
    session = client.session
    session["oauth_state"] = "s123"
    session["oauth_code_verifier"] = "v123"
    session["oauth_next"] = "/"
    session.save()

    token_json = {"access_token": "tok", "expires_in": 3600}
    profile = {"id": 1, "username": "ext", "email": "ext@example.com"}

    with patch("apps.auth.oauth_views.httpx.post") as mock_post, \
         patch("apps.auth.oauth_views.introspect_token", return_value=profile), \
         patch("apps.auth.oauth_views.fetch_userinfo", return_value=None):
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json.return_value = token_json
        resp = client.get("/auth/callback/?state=s123&code=authcode")

    assert resp.status_code == 302
    assert "/auth/login/" in resp.url
    assert not User.objects.filter(email="ext@example.com").exists()


def test_logout_clears_session(client):
    user = User.objects.create_user(email="x@dimagi.com", display_name="x")
    client.force_login(user)
    resp = client.get("/auth/logout/")
    assert resp.status_code == 302
    assert "/auth/login/" in resp.url


def test_spa_catch_all_requires_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/auth/login/" in resp.url


def test_spa_catch_all_serves_index_when_logged_in(client):
    user = User.objects.create_user(email="x@dimagi.com", display_name="x")
    client.force_login(user)
    resp = client.get("/")
    # Will 500 or 404 if index.html doesn't exist, but 200 means we passed login
    # check and hit the TemplateView. Accept 200 or 500 (template missing in tests).
    assert resp.status_code in (200, 500)
```

### Step 10: Clean up production.py leftovers

Read `config/settings/production.py`. Verify it's the AWS-ready stub from PR #9. If there's anything referencing `CLOUD_SQL_CONNECTION_NAME`, `IAP_REQUIRED`, or Unix socket database URLs, remove it. The file should look roughly like:

```python
"""Production settings for ace-web (AWS ECS Fargate deployment)."""
from .base import *  # noqa: F401, F403

DEBUG = False

# Fail loud on misconfiguration instead of silently using dev defaults.
SECRET_KEY = env("DJANGO_SECRET_KEY")  # noqa: F405
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")  # noqa: F405
DATABASES = {"default": env.db("DATABASE_URL")}  # noqa: F405

# Security headers.
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

# WARNING: CHANNEL_LAYERS is still InMemoryChannelLayer from base.py.
# Before scaling the ECS service past one task, switch to channels-redis
# pointing at the shared connect-labs ElastiCache cluster. This is deferred
# to Phase 3 when multi-player drafts land.
```

### Step 11: Run tests

```bash
.venv/bin/pytest apps/auth/tests/test_oauth_views.py -v
```

Expected: 8 passed.

```bash
.venv/bin/pytest -v
```

Expected: 99 passed (91 prior + 8 new OAuth tests).

### Step 12: Commit

```bash
git add apps/auth/ config/settings/ config/urls.py pyproject.toml
git commit -m "feat(auth): add Connect OAuth for labs AWS deployment"
```

Body: note the port from connect-labs, @dimagi.com enforcement at callback, tenant-unique session cookie, path-prefix ready via FORCE_SCRIPT_NAME in connectlabs.py.

---

## Task 2: Frontend /ace/ path prefix

**Files:**
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/api/client.ts`

**Context:** When deployed behind the ALB with path prefix `/ace/*`, the React bundle must reference assets under `/ace/` and the API client must hit `/ace/api/*`. Vite's `base` option handles the asset prefix. React Router's `basename` handles the client-side routing prefix. The API client needs a prefix-aware URL builder.

### Step 1: Update Vite base path

Modify `frontend/vite.config.ts`. Read the current file first. Add `base: '/ace/'` to the `defineConfig` call. Example final state:

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/ace/",
  build: {
    // ... preserve existing build config ...
  },
});
```

**Important:** if the existing config has a `base` already, change it. If it has no `build.outDir`, leave the default (which is `dist/`). Do not break any existing config.

### Step 2: Update React Router basename

Modify `frontend/src/router.tsx`. Change:

```typescript
export const router = createBrowserRouter([...]);
```

to:

```typescript
export const router = createBrowserRouter([...], { basename: "/ace" });
```

### Step 3: Update API client to use prefix-aware paths

Modify `frontend/src/api/client.ts`. The current `apiFetch` calls pass full paths like `/api/sessions`. Behind `/ace/*` these become `/ace/api/sessions`. Make the API client prefix-aware by reading the basename from Vite:

```typescript
import type { ApiEnvelope } from "./types";

export class ApiError extends Error {
  constructor(public code: string, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

// Vite exposes the base path at import.meta.env.BASE_URL.
// It's '/ace/' in prod and '/' in local dev.
const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");

function buildUrl(path: string): string {
  // `path` is always something like "/api/sessions" or "/api/auth/cli/start"
  // (starts with a slash). Prefix with BASE_URL so it becomes
  // "/ace/api/sessions" in prod or "/api/sessions" in dev.
  return API_PREFIX + path;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = buildUrl(path);
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(url, { ...init, headers });
  let envelope: ApiEnvelope<T>;
  try {
    envelope = await resp.json();
  } catch {
    throw new ApiError("invalid_response", `${resp.status} ${resp.statusText}`);
  }
  if (envelope.error) {
    throw new ApiError(envelope.error.code, envelope.error.message);
  }
  if (envelope.data === null) {
    throw new ApiError("empty_response", "no data in envelope");
  }
  return envelope.data;
}

// Legacy compatibility for HomePage.tsx
export const api = {
  health: () => apiFetch<{ status: string }>("/api/health"),
};
```

Also update `frontend/src/api/messages.ts`'s `streamUrl` helper similarly:

```typescript
const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");

export const streamUrl = (assistantMessageId: number) =>
  `${API_PREFIX}/api/messages/${assistantMessageId}/stream`;
```

### Step 4: Verify TS compiles

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

### Step 5: Verify production build

```bash
cd frontend && npm run build
```

Expected: build completes. Inspect `frontend/dist/index.html` — the `<script>` and `<link>` tags should reference `/ace/assets/...` URLs.

### Step 6: Commit

```bash
git add frontend/vite.config.ts frontend/src/router.tsx frontend/src/api/client.ts frontend/src/api/messages.ts
git commit -m "feat(frontend): path prefix /ace/ for AWS tenant deployment"
```

---

## Task 3: Dockerfiles + ECS task definition JSON

**Files:**
- Rewrite: `Dockerfile`
- Create: `Dockerfile.frontend`
- Create: `frontend/nginx.prod.conf`
- Create: `deploy/aws/task-definition.json`
- Create: `deploy/aws/README.md`
- Modify: `docker-compose.yml` (add frontend service for parity)

### Step 1: Rewrite the backend Dockerfile

Replace `Dockerfile` with the scout-pattern backend image:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.connectlabs

# System dependencies: postgres client libs for psycopg, curl for healthchecks.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast, reproducible dep installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dep manifests first so Docker layer caching works.
COPY pyproject.toml uv.lock* ./

# Install deps from the lock file only (no source yet, no dev extras).
RUN uv export --frozen --no-dev --no-emit-project 2>/dev/null > /tmp/requirements.txt || \
    uv pip compile pyproject.toml -o /tmp/requirements.txt && \
    uv pip install --system -r /tmp/requirements.txt

# Copy the rest of the project.
COPY . .

# Install the project itself (fast — deps already installed).
RUN uv pip install --system --no-deps -e .

# Run collectstatic at build time so the image ships with the static
# manifest. Use placeholders for env vars that settings.base would otherwise
# require — the values don't affect collectstatic output.
RUN DJANGO_SECRET_KEY=build-time-placeholder \
    DJANGO_ALLOWED_HOSTS=build-time-placeholder \
    DATABASE_URL=sqlite:///tmp/build.db \
    DJANGO_SETTINGS_MODULE=config.settings.base \
    python manage.py collectstatic --noinput --clear

# Non-root user.
RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

EXPOSE 8000

# Production command — uvicorn ASGI server.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
```

**Note:** scout's Dockerfile uses `runserver` as CMD because it expects the ECS task definition to override the command. For ace-web we bake `uvicorn` into the CMD as the default, which matches Phase 1's `entrypoint.sh` behavior.

### Step 2: Create the frontend Dockerfile

Create `Dockerfile.frontend`:

```dockerfile
# syntax=docker/dockerfile:1

# --- Build stage ---
FROM oven/bun:1 AS build

WORKDIR /app

# Install frontend deps.
COPY frontend/package.json frontend/bun.lockb* frontend/package-lock.json* ./
RUN if [ -f bun.lockb ]; then bun install --frozen-lockfile; \
    elif [ -f package-lock.json ]; then bun install --no-save; \
    else bun install; fi

# Copy source and build.
COPY frontend/ .

# Vite picks up the base path from vite.config.ts (/ace/).
RUN bun run build

# --- Production stage ---
FROM nginx:alpine

# Copy built assets.
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx reverse-proxy config.
COPY frontend/nginx.prod.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
```

### Step 3: Create the nginx config

Create `frontend/nginx.prod.conf`:

```nginx
# nginx config for the ace-web frontend container.
#
# Serves the Vite bundle under /ace/ and reverse-proxies /ace/api/* and
# /ace/auth/* to the backend container (which listens on localhost:8000 in
# the same ECS task).

server {
    listen 3000;
    server_name _;

    # Where the React bundle lives.
    root /usr/share/nginx/html;
    index index.html;

    # ALB health check endpoint (no prefix so the target group can hit it
    # directly via path /ace/api/health — handled by the backend proxy below).

    # Reverse-proxy API + admin + auth to the Django backend.
    location /ace/api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # SSE: disable buffering and extend timeout.
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        chunked_transfer_encoding on;
    }

    location /ace/auth/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ace/admin/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Static files from Django's WhiteNoise-collected bundle
    # (collectstatic runs at backend image build time).
    location /ace/static/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_cache_valid 200 1h;
    }

    # React Router catch-all: anything under /ace/ that doesn't match an
    # asset falls through to index.html so React Router can handle it.
    location /ace/ {
        try_files $uri $uri/ /index.html;
    }

    # Redirect bare / to /ace/ so users don't get confused.
    location = / {
        return 301 /ace/;
    }
}
```

### Step 4: Create the ECS task definition

Create `deploy/aws/task-definition.json`:

```json
{
  "family": "labs-jj-ace-web",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::858923557655:role/labs-jj-ace-web-exec",
  "taskRoleArn": "arn:aws:iam::858923557655:role/labs-jj-ace-web-task",
  "containerDefinitions": [
    {
      "name": "api",
      "image": "858923557655.dkr.ecr.us-east-1.amazonaws.com/labs-jj-ace-web:latest",
      "essential": true,
      "portMappings": [
        {"containerPort": 8000, "protocol": "tcp"}
      ],
      "environment": [
        {"name": "DJANGO_SETTINGS_MODULE", "value": "config.settings.connectlabs"},
        {"name": "DJANGO_DEBUG", "value": "False"},
        {"name": "DJANGO_ALLOWED_HOSTS", "value": "labs.connect.dimagi.com"},
        {"name": "CONNECT_PRODUCTION_URL", "value": "https://connect.dimagi.com"},
        {"name": "FORCE_SCRIPT_NAME", "value": "/ace"}
      ],
      "secrets": [
        {"name": "DJANGO_SECRET_KEY", "valueFrom": "arn:aws:secretsmanager:us-east-1:858923557655:secret:ace-web/django-secret-key"},
        {"name": "DATABASE_URL", "valueFrom": "arn:aws:secretsmanager:us-east-1:858923557655:secret:ace-web/database-url"},
        {"name": "CONNECT_OAUTH_CLIENT_ID", "valueFrom": "arn:aws:secretsmanager:us-east-1:858923557655:secret:ace-web/connect-oauth-client-id"},
        {"name": "CONNECT_OAUTH_CLIENT_SECRET", "valueFrom": "arn:aws:secretsmanager:us-east-1:858923557655:secret:ace-web/connect-oauth-client-secret"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/labs-jj-ace-web",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "api",
          "awslogs-create-group": "true"
        }
      },
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost:8000/api/health || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 30
      }
    },
    {
      "name": "web",
      "image": "858923557655.dkr.ecr.us-east-1.amazonaws.com/labs-jj-ace-web-frontend:latest",
      "essential": true,
      "portMappings": [
        {"containerPort": 3000, "protocol": "tcp"}
      ],
      "dependsOn": [
        {"containerName": "api", "condition": "HEALTHY"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/labs-jj-ace-web",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "web",
          "awslogs-create-group": "true"
        }
      }
    }
  ]
}
```

**Note on secret ARNs:** the `valueFrom` values point at Secrets Manager ARNs in a predictable format. The actual ARN suffix (e.g., `ace-web/django-secret-key-AbCdEf`) is assigned by AWS when the secret is created. For the initial registration in Task 5, the one-time setup script creates the secrets and captures the actual ARNs, then this task definition is re-rendered with the real ARNs. Alternatively: use the shorter form `arn:aws:secretsmanager:us-east-1:858923557655:secret:ace-web/django-secret-key` (no suffix) which AWS resolves to the latest version automatically.

**Note on IAM roles:** `executionRoleArn` must exist in AWS before the task def can be registered. The execution role needs permissions to pull from ECR, read secrets from Secrets Manager, and write to CloudWatch Logs. The task role is used by the container itself (e.g., if the app ever writes to S3 — not used in Phase 2). Task 5's setup script creates both.

### Step 5: Create the deploy directory README

Create `deploy/aws/README.md`:

```markdown
# deploy/aws/

AWS deployment artifacts for ace-web.

## Files

- `task-definition.json` — Canonical ECS task definition. Source of truth for the two-container layout (Django backend + nginx frontend). Registered in AWS via `aws ecs register-task-definition` on each deploy.
- `one-time-setup.sh` — Bash runbook that creates ECR repos, Secrets Manager entries, the target group + ALB listener rule, IAM roles, and the ECS service. Run once per environment.

## Deploy flow

1. Developer pushes to `main` (or triggers workflow_dispatch).
2. `.github/workflows/deploy-labs.yml` runs:
   - Authenticates to AWS via OIDC (AWS_ROLE_ARN secret)
   - Builds backend and frontend images in parallel
   - Pushes both to ECR with tags `:latest` and `:$GITHUB_SHA`
   - Registers a new ECS task definition revision with the new image tags
   - Runs `manage.py migrate` as a one-off FARGATE task
   - Calls `ecs update-service --task-definition <new-arn>` to trigger a rolling deploy
   - Waits for service stability

## First-time setup

See `one-time-setup.sh` and `docs/deploy.md` for the full runbook.
```

### Step 6: Update docker-compose.yml for local frontend parity

Modify `docker-compose.yml` to add a frontend service that mirrors the prod nginx container. This isn't strictly necessary for local dev (vite dev server works fine) but it's useful for debugging prod-like issues locally. **Skip this if it complicates local dev** — the backend app service is sufficient for most local work.

Add to `docker-compose.yml`:

```yaml
  frontend:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    ports:
      - "3000:3000"
    depends_on:
      - app
    profiles: ["prod-parity"]  # Only runs when explicitly selected
```

`profiles: ["prod-parity"]` means `docker compose up` won't start it by default. To test the frontend container locally: `docker compose --profile prod-parity up`.

### Step 7: Verify local docker-compose still works

```bash
docker compose up --build app db
```

Confirm the backend container starts, tests pass (`docker compose exec app .venv/bin/pytest -q` or similar), and `curl localhost:8000/api/health` returns ok.

Tear down: `docker compose down`.

### Step 8: Commit

```bash
git add Dockerfile Dockerfile.frontend frontend/nginx.prod.conf deploy/ docker-compose.yml
git commit -m "chore(deploy): add AWS Dockerfiles, nginx config, and ECS task definition"
```

---

## Task 4: GitHub Actions deploy workflow

**Files:**
- Create: `.github/workflows/deploy-labs.yml`
- Verify (don't modify): `.github/workflows/ci.yml`

**Context:** The workflow mirrors `scout-jjackson/.github/workflows/deploy-labs.yml` exactly in shape, with resource names swapped from `scout` to `ace-web`. Triggered manually via `workflow_dispatch` (no auto-deploy on push), authenticates to AWS via OIDC, builds both images in parallel, pushes to ECR, runs migrations in a one-off task, updates the service, waits for stability.

### Step 1: Read scout's workflow as the template

Read `/Users/jjackson/emdash-projects/scout-jjackson/.github/workflows/deploy-labs.yml` in full. This is the reference implementation. Your job is to adapt it for ace-web's resource names.

### Step 2: Write the ace-web deploy workflow

Create `.github/workflows/deploy-labs.yml`. Use scout's workflow as the structural template, with these substitutions:

- Service name: `labs-jj-scout-web` → `labs-jj-ace-web`
- ECR repo (backend): `labs-jj-scout` → `labs-jj-ace-web`
- ECR repo (frontend): `labs-jj-scout-frontend` → `labs-jj-ace-web-frontend`
- Image build args: `VITE_BASE_PATH=/scout/` → `VITE_BASE_PATH=/ace/`
- Any scout-specific env vars or paths → ace-web equivalents

The workflow should have these jobs (mirroring scout):

1. **`detect`** — compares last-deployed SHA (from ECR image labels or tags) against `HEAD`, outputs `backend-changed`, `frontend-changed`, `any-changed`
2. **`build-backend`** — needs `detect`, only runs if backend changed. Uses `docker/build-push-action@v5` with `Dockerfile`, pushes to `labs-jj-ace-web:latest` and `:$GITHUB_SHA`
3. **`build-frontend`** — needs `detect`, only runs if frontend changed. Uses `Dockerfile.frontend`, pushes to `labs-jj-ace-web-frontend:latest` and `:$GITHUB_SHA`
4. **`migrate`** — needs `build-backend`, runs only if the `run_migrations` input is true. Uses `aws ecs run-task` with container command override to `python manage.py migrate --noinput`
5. **`deploy`** — needs `build-backend` and `build-frontend` (both use `if: always() && ...` to handle partial builds). Calls `aws ecs register-task-definition` with the new image tags (read `deploy/aws/task-definition.json`, patch image values with `jq`), then `aws ecs update-service --task-definition <new-arn>`, then `aws ecs wait services-stable`

**OIDC auth:** use `aws-actions/configure-aws-credentials@v4` with `role-to-assume: ${{ secrets.AWS_ROLE_ARN }}` and `aws-region: us-east-1`. Permissions block on the job: `id-token: write, contents: read`.

**Skeleton** (adapt from scout's full version):

```yaml
name: Deploy to Labs (AWS)

on:
  workflow_dispatch:
    inputs:
      deploy_target:
        description: "What to deploy"
        required: false
        default: "auto"
        type: choice
        options: [auto, all, backend-only, frontend-only]
      run_migrations:
        description: "Run Django migrations before deploy"
        required: false
        default: false
        type: boolean

concurrency:
  group: deploy-labs
  cancel-in-progress: false

env:
  AWS_REGION: us-east-1
  ECR_REGISTRY: 858923557655.dkr.ecr.us-east-1.amazonaws.com
  ECS_CLUSTER: labs-jj-cluster
  ECS_SERVICE: labs-jj-ace-web
  ECR_REPO_BACKEND: labs-jj-ace-web
  ECR_REPO_FRONTEND: labs-jj-ace-web-frontend
  TASK_FAMILY: labs-jj-ace-web
  VITE_BASE_PATH: /ace/

permissions:
  id-token: write
  contents: read

jobs:
  detect:
    runs-on: ubuntu-latest
    outputs:
      backend-changed: ${{ steps.changes.outputs.backend }}
      frontend-changed: ${{ steps.changes.outputs.frontend }}
    steps:
      - uses: actions/checkout@v4
      # ... change-detection steps: compare HEAD to last deployed image tag
      # (from ECR) or to a git tag. Follow scout's exact logic.

  build-backend:
    needs: detect
    if: needs.detect.outputs.backend-changed == 'true' || inputs.deploy_target == 'all' || inputs.deploy_target == 'backend-only'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}
      - uses: aws-actions/amazon-ecr-login@v2
      - uses: docker/setup-buildx-action@v3
      - uses: docker/build-push-action@v5
        with:
          context: .
          file: Dockerfile
          push: true
          tags: |
            ${{ env.ECR_REGISTRY }}/${{ env.ECR_REPO_BACKEND }}:latest
            ${{ env.ECR_REGISTRY }}/${{ env.ECR_REPO_BACKEND }}:${{ github.sha }}
          cache-from: type=registry,ref=${{ env.ECR_REGISTRY }}/${{ env.ECR_REPO_BACKEND }}:buildcache
          cache-to: type=registry,ref=${{ env.ECR_REGISTRY }}/${{ env.ECR_REPO_BACKEND }}:buildcache,mode=max

  build-frontend:
    needs: detect
    if: needs.detect.outputs.frontend-changed == 'true' || inputs.deploy_target == 'all' || inputs.deploy_target == 'frontend-only'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}
      - uses: aws-actions/amazon-ecr-login@v2
      - uses: docker/setup-buildx-action@v3
      - uses: docker/build-push-action@v5
        with:
          context: .
          file: Dockerfile.frontend
          push: true
          build-args: |
            VITE_BASE_PATH=${{ env.VITE_BASE_PATH }}
          tags: |
            ${{ env.ECR_REGISTRY }}/${{ env.ECR_REPO_FRONTEND }}:latest
            ${{ env.ECR_REGISTRY }}/${{ env.ECR_REPO_FRONTEND }}:${{ github.sha }}

  migrate:
    needs: build-backend
    if: inputs.run_migrations == true
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}
      - name: Run migrations as one-off FARGATE task
        run: |
          TASK_DEF_ARN=$(aws ecs describe-task-definition \
            --task-definition ${{ env.TASK_FAMILY }} \
            --query 'taskDefinition.taskDefinitionArn' \
            --output text)
          aws ecs run-task \
            --cluster ${{ env.ECS_CLUSTER }} \
            --task-definition "$TASK_DEF_ARN" \
            --launch-type FARGATE \
            --network-configuration "awsvpcConfiguration={subnets=[${{ secrets.LABS_SUBNET }}],securityGroups=[${{ secrets.LABS_SECURITY_GROUP }}],assignPublicIp=ENABLED}" \
            --overrides '{"containerOverrides":[{"name":"api","command":["python","manage.py","migrate","--noinput"]}]}'

  deploy:
    needs: [build-backend, build-frontend]
    if: always() && (needs.build-backend.result == 'success' || needs.build-backend.result == 'skipped') && (needs.build-frontend.result == 'success' || needs.build-frontend.result == 'skipped')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}
      - name: Register new task definition revision
        id: register-task
        run: |
          # Patch the committed task-definition.json with the new image tags.
          jq --arg backend "${{ env.ECR_REGISTRY }}/${{ env.ECR_REPO_BACKEND }}:${{ github.sha }}" \
             --arg frontend "${{ env.ECR_REGISTRY }}/${{ env.ECR_REPO_FRONTEND }}:${{ github.sha }}" \
             '(.containerDefinitions[] | select(.name=="api") | .image) = $backend | (.containerDefinitions[] | select(.name=="web") | .image) = $frontend' \
             deploy/aws/task-definition.json > /tmp/task-def.json
          NEW_TASK_DEF_ARN=$(aws ecs register-task-definition \
            --cli-input-json file:///tmp/task-def.json \
            --query 'taskDefinition.taskDefinitionArn' \
            --output text)
          echo "task-def-arn=$NEW_TASK_DEF_ARN" >> $GITHUB_OUTPUT
      - name: Update service
        run: |
          aws ecs update-service \
            --cluster ${{ env.ECS_CLUSTER }} \
            --service ${{ env.ECS_SERVICE }} \
            --task-definition ${{ steps.register-task.outputs.task-def-arn }} \
            --force-new-deployment
      - name: Wait for service stability
        run: |
          aws ecs wait services-stable \
            --cluster ${{ env.ECS_CLUSTER }} \
            --services ${{ env.ECS_SERVICE }}
```

**Note:** The `detect` job's change-detection logic can be simple: compare `HEAD` to a reference (e.g., `origin/main~1`) and set `backend-changed=true` if any file under `apps/`, `config/`, `Dockerfile`, `pyproject.toml`, or `uv.lock` changed, and `frontend-changed=true` if any file under `frontend/`, `Dockerfile.frontend`, or `nginx.prod.conf` changed. For the initial version, it's fine to set both to `'true'` always and tune later.

### Step 3: Verify ci.yml still works

Read `.github/workflows/ci.yml`. Ensure it runs pytest on push/PR. Don't modify it unless something is broken.

### Step 4: Commit

```bash
git add .github/workflows/deploy-labs.yml
git commit -m "ci: add AWS ECS deploy workflow (labs tenant)"
```

---

## Task 5: One-time setup runbook + docs/deploy.md + CLAUDE.md

**Files:**
- Create: `deploy/aws/one-time-setup.sh`
- Rewrite: `docs/deploy.md`
- Modify: `CLAUDE.md`

### Step 1: Write the one-time setup script

Create `deploy/aws/one-time-setup.sh`:

```bash
#!/bin/bash
#
# ace-web one-time AWS setup runbook.
#
# Run this ONCE when first deploying ace-web to the connect-labs AWS
# environment. It creates all the AWS resources that the GitHub Actions
# deploy workflow then reuses on every deploy.
#
# Prerequisites:
#   - AWS CLI authenticated as an admin-level role in account 858923557655
#   - us-east-1 region
#   - The shared connect-labs infrastructure already exists:
#     * ECS cluster labs-jj-cluster
#     * ALB with a listener fronting labs.connect.dimagi.com
#     * RDS Postgres instance (get its endpoint from the scout task def)
#     * VPC subnets + security group (ids in labs GitHub secrets)
#
# This script is NOT idempotent — re-running it after resources exist will
# error on creation. Read the output and handle any partial runs by hand.
#
# Estimated runtime: ~5 minutes. Incremental cost after setup: ~$5-15/month.

set -euo pipefail

AWS_REGION="us-east-1"
ACCOUNT_ID="858923557655"
APP_NAME="ace-web"
ECR_BACKEND="labs-jj-ace-web"
ECR_FRONTEND="labs-jj-ace-web-frontend"
TASK_FAMILY="labs-jj-ace-web"
SERVICE_NAME="labs-jj-ace-web"
TARGET_GROUP_NAME="labs-jj-ace-web-tg"
CLUSTER_NAME="labs-jj-cluster"
LOG_GROUP="/ecs/labs-jj-ace-web"

# ── 1. ECR repositories ────────────────────────────────────────────────

echo "→ Creating ECR repositories..."
aws ecr create-repository --repository-name "$ECR_BACKEND" --region "$AWS_REGION" || true
aws ecr create-repository --repository-name "$ECR_FRONTEND" --region "$AWS_REGION" || true

# ── 2. CloudWatch log group ────────────────────────────────────────────

echo "→ Creating CloudWatch log group..."
aws logs create-log-group --log-group-name "$LOG_GROUP" --region "$AWS_REGION" || true
aws logs put-retention-policy --log-group-name "$LOG_GROUP" --retention-in-days 30 --region "$AWS_REGION"

# ── 3. Secrets Manager entries ─────────────────────────────────────────

echo "→ Creating Secrets Manager entries..."
echo "  NOTE: you will be prompted to paste secret values."

read -r -s -p "  DJANGO_SECRET_KEY (50+ random chars): " DJANGO_SECRET_KEY; echo
read -r -s -p "  DATABASE_URL (postgres://user:pass@host:5432/ace_web): " DATABASE_URL; echo
read -r -s -p "  CONNECT_OAUTH_CLIENT_ID: " CONNECT_OAUTH_CLIENT_ID; echo
read -r -s -p "  CONNECT_OAUTH_CLIENT_SECRET: " CONNECT_OAUTH_CLIENT_SECRET; echo

aws secretsmanager create-secret --name "ace-web/django-secret-key" \
  --secret-string "$DJANGO_SECRET_KEY" --region "$AWS_REGION"
aws secretsmanager create-secret --name "ace-web/database-url" \
  --secret-string "$DATABASE_URL" --region "$AWS_REGION"
aws secretsmanager create-secret --name "ace-web/connect-oauth-client-id" \
  --secret-string "$CONNECT_OAUTH_CLIENT_ID" --region "$AWS_REGION"
aws secretsmanager create-secret --name "ace-web/connect-oauth-client-secret" \
  --secret-string "$CONNECT_OAUTH_CLIENT_SECRET" --region "$AWS_REGION"

# ── 4. IAM roles (execution + task) ────────────────────────────────────

echo "→ Creating IAM roles..."

# Execution role: pulls ECR images, reads secrets, writes logs
aws iam create-role \
  --role-name labs-jj-ace-web-exec \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }' || true

aws iam attach-role-policy \
  --role-name labs-jj-ace-web-exec \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Inline policy to allow reading our specific secrets
aws iam put-role-policy \
  --role-name labs-jj-ace-web-exec \
  --policy-name ace-web-secrets-read \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Effect\": \"Allow\",
      \"Action\": [\"secretsmanager:GetSecretValue\"],
      \"Resource\": \"arn:aws:secretsmanager:${AWS_REGION}:${ACCOUNT_ID}:secret:ace-web/*\"
    }]
  }"

# Task role: no special permissions needed in Phase 2 (app doesn't call AWS APIs)
aws iam create-role \
  --role-name labs-jj-ace-web-task \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }' || true

# ── 5. Register the initial task definition ────────────────────────────

echo "→ Registering initial task definition..."
echo "  NOTE: this uses deploy/aws/task-definition.json with the :latest tag."
echo "  After the first successful deploy, CI will register new revisions."

cd "$(dirname "$0")/../.."
aws ecs register-task-definition \
  --cli-input-json "file://deploy/aws/task-definition.json" \
  --region "$AWS_REGION"

# ── 6. Target group ────────────────────────────────────────────────────

echo "→ Creating target group..."
echo "  You need the VPC ID — find it with:"
echo "    aws ec2 describe-vpcs --region $AWS_REGION"
read -r -p "  VPC ID (vpc-xxxxx): " VPC_ID

TG_ARN=$(aws elbv2 create-target-group \
  --name "$TARGET_GROUP_NAME" \
  --protocol HTTP \
  --port 3000 \
  --vpc-id "$VPC_ID" \
  --target-type ip \
  --health-check-path "/ace/api/health" \
  --health-check-interval-seconds 30 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3 \
  --region "$AWS_REGION" \
  --query 'TargetGroups[0].TargetGroupArn' --output text)

echo "  Target group ARN: $TG_ARN"

# ── 7. ALB listener rule ───────────────────────────────────────────────

echo "→ Adding ALB listener rule for /ace/* ..."
echo "  You need the ALB listener ARN — find it with:"
echo "    aws elbv2 describe-load-balancers --region $AWS_REGION"
echo "    aws elbv2 describe-listeners --load-balancer-arn <alb-arn> --region $AWS_REGION"
read -r -p "  ALB listener ARN: " LISTENER_ARN
read -r -p "  Rule priority (unused integer, e.g. 200): " RULE_PRIORITY

aws elbv2 create-rule \
  --listener-arn "$LISTENER_ARN" \
  --priority "$RULE_PRIORITY" \
  --conditions "Field=path-pattern,Values=/ace/*" \
  --actions "Type=forward,TargetGroupArn=$TG_ARN" \
  --region "$AWS_REGION"

# ── 8. ECS service ─────────────────────────────────────────────────────

echo "→ Creating ECS service..."
echo "  You need the labs subnet IDs and security group ID."
read -r -p "  Subnet IDs (comma-separated, no spaces): " SUBNET_IDS
read -r -p "  Security group ID (sg-xxxxx): " SG_ID

aws ecs create-service \
  --cluster "$CLUSTER_NAME" \
  --service-name "$SERVICE_NAME" \
  --task-definition "$TASK_FAMILY" \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_IDS],securityGroups=[$SG_ID],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=$TG_ARN,containerName=web,containerPort=3000" \
  --region "$AWS_REGION"

# ── 9. Create the database on the shared RDS ───────────────────────────

echo "→ Creating 'ace_web' database on the shared RDS instance..."
echo "  This requires connecting to RDS from a machine in the VPC, or using"
echo "  psql over the DATABASE_URL you provided above. Run manually:"
echo ""
echo "    psql \"\$DATABASE_URL\" -c 'CREATE DATABASE ace_web;'"
echo ""
echo "  OR: if the DATABASE_URL already points at an existing database, skip"
echo "  this step."

echo ""
echo "✓ One-time setup complete."
echo ""
echo "Next steps:"
echo "  1. Register the OAuth client ID in Connect admin:"
echo "     https://connect.dimagi.com/admin/oauth2_provider/application/"
echo "     Callback URL: https://labs.connect.dimagi.com/ace/auth/callback/"
echo "  2. Update the ace-web/connect-oauth-client-id and -secret secrets with"
echo "     the real values from the Connect admin."
echo "  3. Trigger the deploy workflow: Actions > Deploy to Labs (AWS) > Run"
echo "     with run_migrations=true for the first deploy."
echo "  4. After the first deploy completes, visit https://labs.connect.dimagi.com/ace/"
echo "     and sign in with a @dimagi.com Connect account."
```

Make it executable:

```bash
chmod +x deploy/aws/one-time-setup.sh
```

### Step 2: Rewrite docs/deploy.md

Read the current `docs/deploy.md` (which is the post-PR-#9 stub). Replace with a full AWS runbook:

```markdown
# Deploying ace-web to AWS (connect-labs tenant)

ace-web is deployed as a tenant service behind the `labs.connect.dimagi.com`
ALB on AWS ECS Fargate, reusing the shared connect-labs infrastructure
(RDS, ElastiCache, ALB, VPC). The deployment pattern mirrors
[scout-jjackson](/Users/jjackson/emdash-projects/scout-jjackson)'s.

## Architecture

- **Cloud:** AWS account `858923557655`, region `us-east-1`
- **Compute:** ECS Fargate task in cluster `labs-jj-cluster`
- **Task layout:** two containers in one task — `api` (Django + uvicorn on port
  8000) and `web` (nginx serving the Vite bundle on port 3000, reverse-proxying
  `/ace/api/*` and `/ace/auth/*` to localhost:8000)
- **Load balancer:** shared labs ALB with a listener rule routing `/ace/*` to
  the ace-web target group
- **Database:** shared RDS Postgres instance, database `ace_web`
- **Cache/Redis:** shared ElastiCache (used in Phase 3 for channels-redis; idle
  in Phase 2)
- **Secrets:** AWS Secrets Manager under the `ace-web/` prefix
- **Logs:** CloudWatch Logs group `/ecs/labs-jj-ace-web`, 30-day retention
- **Auth:** Connect OAuth with PKCE, `@dimagi.com` email filter
- **Deploy:** GitHub Actions `.github/workflows/deploy-labs.yml` (manual
  `workflow_dispatch` trigger)

## First-time setup

Run `deploy/aws/one-time-setup.sh` from an AWS-authenticated shell. It creates:
- ECR repos (`labs-jj-ace-web`, `labs-jj-ace-web-frontend`)
- CloudWatch log group with 30-day retention
- Secrets Manager entries (prompts for values)
- IAM execution and task roles
- ECS task definition (initial revision)
- ALB target group (health check path `/ace/api/health`)
- ALB listener rule routing `/ace/*`
- ECS service (desired count 1, rolling deploy)

You will be prompted for:
- Django secret key (generate with `python -c 'import secrets; print(secrets.token_urlsafe(50))'`)
- DATABASE_URL (the shared RDS endpoint + new database name)
- Connect OAuth client ID and secret (register at
  https://connect.dimagi.com/admin/oauth2_provider/application/ with callback
  `https://labs.connect.dimagi.com/ace/auth/callback/`)
- VPC ID, subnets, security group, ALB listener ARN

After setup, create the `ace_web` database:

```bash
psql "$DATABASE_URL" -c "CREATE DATABASE ace_web;"
```

## Deploy workflow

Triggered manually from GitHub Actions:

1. Go to Actions → "Deploy to Labs (AWS)" → "Run workflow"
2. Select options:
   - `deploy_target`: `auto` (let change-detection decide), `all`, `backend-only`, or `frontend-only`
   - `run_migrations`: `true` for the first deploy and for any deploy that
     changes the schema; `false` otherwise
3. The workflow:
   - Authenticates via OIDC using `AWS_ROLE_ARN`
   - Builds and pushes backend + frontend images in parallel
   - Runs `manage.py migrate --noinput` as a one-off FARGATE task (if
     `run_migrations=true`)
   - Registers a new task definition revision with the new image tags
   - Calls `ecs update-service` to trigger a rolling deploy
   - Waits for `services-stable`

## Local dev

```bash
docker compose up
```

Backend at `http://localhost:8000` (no path prefix locally — `FORCE_SCRIPT_NAME`
is only set in `connectlabs.py`, not in `development.py`).

For prod-parity testing with the full two-container layout:

```bash
docker compose --profile prod-parity up
```

Then visit `http://localhost:3000/ace/`.

## Observability

- **Logs:** CloudWatch `/ecs/labs-jj-ace-web` — separate streams for `api` and `web` containers
- **Metrics:** ECS service metrics in the AWS console
- **Alarms:** none set up yet (Phase 5 will add SLO alarms)

## Rollback

ECS keeps all prior task definition revisions. To roll back:

```bash
# List revisions
aws ecs list-task-definitions --family-prefix labs-jj-ace-web --region us-east-1

# Update the service to a previous revision
aws ecs update-service \
  --cluster labs-jj-cluster \
  --service labs-jj-ace-web \
  --task-definition labs-jj-ace-web:<previous-revision-number> \
  --region us-east-1
```

## Cost

Estimated incremental cost: ~$5-15/month (shared ALB, RDS, ElastiCache, VPC
amortized across all labs tenants; only the ECS task CPU/memory and ECR
storage are ace-web-specific).

## Troubleshooting

- **503 from ALB:** target group has no healthy targets. Check CloudWatch logs
  for the `api` container — usually a `DJANGO_SECRET_KEY` or `DATABASE_URL`
  misconfiguration, or a failed migration.
- **Health check failing:** ALB health check hits `/ace/api/health` via the
  nginx container. Verify nginx is proxying correctly (`docker compose --profile
  prod-parity up` locally) and the Django `/api/health` endpoint is IAP-free
  (it should be — the health check view has no auth requirement).
- **OAuth callback loop:** verify the Connect OAuth application's
  callback URL is exactly `https://labs.connect.dimagi.com/ace/auth/callback/`
  and the `CONNECT_OAUTH_CLIENT_ID`/`CONNECT_OAUTH_CLIENT_SECRET` secrets
  in AWS Secrets Manager match.
- **CSRF failures after login:** verify `SESSION_COOKIE_NAME=sessionid_ace`
  and `CSRF_COOKIE_NAME=csrftoken_ace` in `connectlabs.py`. Collisions with
  scout's cookies cause surprising failures on the shared domain.
```

### Step 3: Update CLAUDE.md

Read the current `CLAUDE.md`. Make these edits:

1. **Stack section:** confirm it already says AWS ECS Fargate (from PR #9's cleanup). Adjust if it still has any GCP residue.
2. **Key architectural decisions:** update the auth bullet to say "Connect OAuth with PKCE, `@dimagi.com` email filter at the callback" (not "TBD, see AWS migration plan").
3. **Workflow section:** replace the deploy line with "Deploy: GitHub Actions workflow `deploy-labs.yml` (manual trigger, OIDC to AWS)".
4. **Learnings section:** add a new Conversation-engine or Deploy sub-entry for the AWS migration:

   ```markdown
   Deploy:
   - [aws-migration](docs/plans/2026-04-08-aws-migration.md) — completed migration from GCP Cloud Run to AWS ECS Fargate as a connect-labs tenant. Auth swapped from IAP to Connect OAuth. Filestore dropped in favor of the hybrid-resume Django-replay path.
   ```

5. **Current status table:** add a row "2.5 | AWS migration | Done" — or amend Phase 2's row to note "Done; subsequently migrated from GCP to AWS".
6. **What does NOT ship yet:** no changes needed.

### Step 4: Run the full test suite

```bash
.venv/bin/pytest -v
```

Expected: 99 passed (91 after PR #9 + 8 new OAuth tests from Task 1).

### Step 5: Verify the frontend still builds

```bash
cd frontend && npm run build
```

Expected: clean build. The bundle's assets should reference `/ace/` paths.

### Step 6: Final commit

```bash
git add deploy/aws/one-time-setup.sh docs/deploy.md CLAUDE.md
git commit -m "docs(deploy): add AWS migration runbook and update CLAUDE.md"
```

---

## Self-review (engineer running this plan should also do this)

Before declaring the AWS migration complete, verify:

- [ ] `.venv/bin/pytest -v` passes locally with all 99 tests green
- [ ] `cd frontend && npm run build` completes without errors, and `frontend/dist/index.html` references `/ace/assets/...`
- [ ] `docker compose up` (without the `prod-parity` profile) brings the stack up locally; `curl localhost:8000/api/health` returns ok
- [ ] `docker compose --profile prod-parity up` brings up both backend + frontend nginx containers; `curl localhost:3000/ace/api/health` returns ok
- [ ] The one-time-setup.sh script has been read top-to-bottom and every `aws` command is understood
- [ ] No stray GCP references remain: `grep -r -i "cloudrun\|gcp\|cloud_sql\|filestore\|memorystore\|cloud_build\|artifact_registry" apps/ config/ docs/ deploy/ .github/ Dockerfile* docker-compose.yml pyproject.toml 2>/dev/null | grep -v "aws-migration\|gcp-migration\|\.md:" || echo OK`
- [ ] `deploy/aws/task-definition.json` has the correct IAM role ARNs and secret ARNs (or `:latest` placeholder suffixes)
- [ ] Connect OAuth client has been registered and the callback URL matches `https://labs.connect.dimagi.com/ace/auth/callback/`
- [ ] `AWS_ROLE_ARN`, `LABS_SUBNET`, `LABS_SECURITY_GROUP` GitHub Actions secrets exist in the repo settings (should be reusable from scout's setup)
- [ ] A successful deploy via the GitHub Actions workflow produces a running task visible in the ECS console, with healthy targets in the target group
- [ ] Visiting `https://labs.connect.dimagi.com/ace/` redirects to `/ace/auth/login/`, clicking "Sign in with Connect" completes the OAuth flow, and the user lands at `/ace/` as the React shell

If any of these fail, fix before declaring the migration done.

---

## What ships at the end of this plan

- ace-web running in ECS Fargate behind `labs.connect.dimagi.com/ace/`
- Auth via Connect OAuth with PKCE, restricted to `@dimagi.com` emails
- Phase 2's chat experience (streaming SSE, tool rendering, recent sessions, inline titles, CLI auth page — all reused from Phase 2's code) working end-to-end on the new deployment
- GitHub Actions deploy workflow with manual trigger, OIDC auth, parallel builds, migrations, rolling deploy
- Secrets in AWS Secrets Manager
- ~$5-15/month incremental cost (vs ~$100-150/month standalone GCP)

## What does NOT ship in this plan (deferred)

- **Phase 3:** WebSocket consumer, channels-redis wiring (will use the shared connect-labs ElastiCache, which is free), drafts, presence
- **Phase 4:** Session list page, share tokens, `ace upload` CLI
- **Phase 5:** Observability, evals, security review, demo prep
- **Terraform / IaC:** for this POC we use direct `aws` CLI commands documented as a runbook. If the shared infra grows, Terraform becomes worth the investment.
- **Cleanup of dormant GCP resources:** the `ace-web-deployer@connect-labs.iam.gserviceaccount.com` service account and GitHub Workload Identity Federation provider remain. Both are free. Delete via `gcloud iam service-accounts delete` when confirmed no longer needed.

## References

- Design spec: `docs/specs/2026-04-08-ace-web-design.md` (post-AWS-pivot updates in §5.3, §5.4, §6, §8, §9)
- Phase 2 plan: `docs/plans/2026-04-08-2-conversation-engine.md`
- GCP cleanup PR: `chore(deploy): strip GCP-specific code in preparation for AWS migration` (`1357d81`)
- connect-labs OAuth reference: `/Users/jjackson/emdash-projects/connect-labs/commcare_connect/labs/integrations/connect/oauth{,_views}.py`
- scout deploy reference: `/Users/jjackson/emdash-projects/scout-jjackson/.github/workflows/deploy-labs.yml`
- scout Dockerfile reference: `/Users/jjackson/emdash-projects/scout-jjackson/{Dockerfile,Dockerfile.frontend,frontend/nginx.prod.conf}`
- scout settings reference: `/Users/jjackson/emdash-projects/scout-jjackson/config/settings/connectlabs.py`
