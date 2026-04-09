# ACE Web Harness — Phase 3: Multi-player Collaboration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two `@dimagi.com` teammates can sit in the same `Session`, collaboratively draft the next prompt with turn-taking hand-off, watch the same streaming assistant response, see each other's live presence, and stop a bad response mid-stream. WebSocket is the only chat transport; the Phase 2 SSE + REST-send path is deleted.

**Architecture:** A single `SessionConsumer` (Channels `AsyncJsonWebsocketConsumer`) owns the socket at `ws://…/ws/sessions/<slug>/`. It authenticates via a new ASGI middleware that reads the tenant-specific `sessionid_ace` cookie, checks a `SessionParticipant` row, and dispatches client `{action}` frames to pure helper modules (`drafts.py`, `presence.py`, `turn_driver.py`). The assistant streaming loop is lifted from `streaming.py` into `turn_driver.py` and called from the consumer instead of the SSE view. `channels-redis` points at shared connect-labs ElastiCache; presence lives in a Redis HASH; cross-task stop signals use a Redis string key polled by the turn driver. `docker-compose` gains a `redis:7-alpine` service so dev exercises the same code path as prod.

**Tech Stack:** Python 3.11+, Django 5.x + Channels 4.x + channels-redis 4.2, asyncio, `fakeredis` (test dep), React 19 + Vite + TypeScript + Tailwind, native browser `WebSocket`. No CRDT library.

**Spec reference:** `docs/specs/2026-04-09-phase-3-multi-player-design.md` — read all sections before starting. Whole-vision spec §4.3 / §5.2 / §5.3 are the secondary reference.

**Plan 1 / Plan 2 corrections to keep in mind:**
- All API responses use `apps.common.envelope.success_response` / `error_response` (`{data, error}`).
- `Message.started_at` is `null=True`, set explicitly by the consumer when streaming begins. Never `auto_now_add`.
- The `unique_session_turn` constraint means every `tool_use` / `tool_result` row gets its own monotonically-increasing `turn_index`, not shared with the parent assistant turn.
- `Session.save()` retries slug collisions internally via savepoint — call `Session.objects.create()` normally.
- `SessionParticipant.one_next_per_session` partial unique constraint on `drafts` means the "open next draft" singleton is enforced at the DB level. Trust it.
- `connectlabs.py` is the active AWS settings module; `production.py` is shared base with the security headers. Any `CHANNEL_LAYERS` change must survive the `from .production import *` inheritance.

---

## File structure (created across all tasks)

```
ace-web/
├── apps/
│   ├── sessions/
│   │   ├── consumers.py          # NEW — SessionConsumer, protocol-only dispatch
│   │   ├── turn_driver.py        # NEW — drive_assistant_turn() + helpers lifted from streaming.py
│   │   ├── drafts.py             # NEW — state machine: update_body, claim_lock, commit, discard
│   │   ├── presence.py           # NEW — Redis HASH presence + debounced last_seen write
│   │   ├── routing.py            # MODIFIED — real websocket_urlpatterns
│   │   ├── streaming.py          # DELETED
│   │   ├── views.py              # MODIFIED — drop send_message; add messages_list; add participant_collection
│   │   ├── serializers.py        # MODIFIED — add DraftSerializer, ParticipantSerializer
│   │   ├── urls.py               # MODIFIED — drop message_stream; swap send_message route; add participants route
│   │   └── tests/
│   │       ├── test_consumers.py      # NEW
│   │       ├── test_turn_driver.py    # NEW
│   │       ├── test_drafts.py         # NEW
│   │       ├── test_presence.py       # NEW
│   │       ├── test_views.py          # MODIFIED — drop send_message cases, add messages GET + participants
│   │       └── test_streaming.py      # DELETED
│   │
│   └── common/
│       ├── channels_auth.py      # NEW — AceSessionAuthMiddleware
│       ├── redis_client.py       # NEW — get_redis() shared async client
│       └── tests/
│           ├── test_channels_auth.py  # NEW
│           └── test_redis_client.py   # NEW
│
├── config/
│   ├── asgi.py                   # MODIFIED — wrap router in AceSessionAuthMiddleware
│   ├── settings/
│   │   ├── base.py               # MODIFIED — CHANNEL_LAYERS → RedisChannelLayer, REDIS_URL
│   │   ├── connectlabs.py        # MODIFIED — REDIS_URL from env; comment update
│   │   ├── production.py         # MODIFIED — drop the InMemoryChannelLayer warning comment
│   │   └── test.py               # MODIFIED — override CHANNEL_LAYERS back to InMemoryChannelLayer
│   └── urls.py                   # unchanged
│
├── frontend/
│   └── src/
│       ├── hooks/
│       │   ├── useSessionSocket.ts     # NEW — the one WebSocket-owning hook
│       │   └── useStreamingMessage.ts  # DELETED
│       ├── api/
│       │   ├── messages.ts             # MODIFIED — sendMessage helper deleted; listMessages GET added
│       │   ├── participants.ts         # NEW — addParticipant
│       │   └── types.ts                # MODIFIED — Draft, Participant, WsAction, WsEvent types
│       ├── components/
│       │   ├── PresenceChips.tsx       # NEW
│       │   ├── AddTeammateButton.tsx   # NEW
│       │   ├── SendBox.tsx             # MODIFIED — bound to active draft, soft-lock behavior
│       │   ├── MessageList.tsx         # MODIFIED — reads from session state, not a separate hook
│       │   └── MessageItem.tsx         # unchanged
│       └── pages/
│           └── ChatPage.tsx            # MODIFIED — uses useSessionSocket
│
├── docker-compose.yml            # MODIFIED — add redis:7-alpine, REDIS_URL on web env
├── pyproject.toml                # MODIFIED — + channels-redis, + fakeredis (dev)
├── deploy/aws/task-definition.json  # MODIFIED — add REDIS_URL env from secrets
│
└── docs/
    ├── learnings/
    │   ├── channels-single-instance.md   # MODIFIED — mark resolved, point at new learnings
    │   ├── channels-websocket-auth.md    # NEW
    │   └── redis-presence-hash.md        # NEW
    ├── deploy.md                          # MODIFIED — Redis/ElastiCache section
    └── plans/
        └── 2026-04-09-3-multi-player.md  # THIS FILE
```

---

## Task 1: Add dependencies and Redis infra

**Files:**
- Modify: `pyproject.toml`
- Modify: `docker-compose.yml`
- Create: `apps/common/redis_client.py`
- Create: `apps/common/tests/test_redis_client.py`

- [ ] **Step 1.1: Write the failing test for the Redis client module**

Create `apps/common/tests/test_redis_client.py`:

```python
"""Smoke tests for the shared Redis client factory."""
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_get_redis_returns_same_instance_on_repeat_calls(settings):
    """The module caches one client per process so we don't leak pools."""
    settings.ACE_REDIS_URL = "redis://localhost:6379/0"
    from apps.common import redis_client

    # Reset the module-level cache to avoid leaking state from other tests.
    redis_client._client = None

    with patch("apps.common.redis_client.redis.asyncio.from_url") as from_url:
        fake = object()
        from_url.return_value = fake
        first = await redis_client.get_redis()
        second = await redis_client.get_redis()
        assert first is fake
        assert second is fake
        assert from_url.call_count == 1


@pytest.mark.asyncio
async def test_get_redis_reads_ace_redis_url(settings):
    settings.ACE_REDIS_URL = "redis://example:6379/7"
    from apps.common import redis_client

    redis_client._client = None
    with patch("apps.common.redis_client.redis.asyncio.from_url") as from_url:
        await redis_client.get_redis()
        from_url.assert_called_once_with(
            "redis://example:6379/7", decode_responses=True
        )
```

- [ ] **Step 1.2: Run the test — expect import failure**

Run: `pytest apps/common/tests/test_redis_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.common.redis_client'` or similar — the module does not exist yet.

- [ ] **Step 1.3: Add `channels-redis` and `fakeredis` to `pyproject.toml`**

Modify `pyproject.toml`:

```toml
[project]
name = "ace-web"
version = "0.1.0"
description = "Web harness for the ACE initiative"
requires-python = ">=3.11"
dependencies = [
    "channels>=4.1",
    "channels-redis>=4.2",
    "cryptography>=42",
    "django-environ>=0.11",
    "django>=5.0,<6.0",
    "djangorestframework>=3.15",
    "google-api-python-client>=2.130",
    "google-auth>=2.30",
    "httpx[http2]>=0.27",
    "psycopg[binary]>=3.2",
    "pyyaml>=6.0",
    "uvicorn[standard]>=0.30",
    "whitenoise>=6.7",
]

[project.optional-dependencies]
dev = [
    "fakeredis[aiohttp]>=2.23",
    "pytest>=8.0",
    "pytest-django>=4.8",
    "pytest-asyncio>=0.23",
    "ruff>=0.5",
    "ipython",
]
```

(Everything below `[project.optional-dependencies]` is unchanged — keep `setuptools.packages.find`, `pytest.ini_options`, and `ruff` sections exactly as they are.)

- [ ] **Step 1.4: Reinstall dependencies in the container**

Run: `docker compose build app` (or `pip install -e ".[dev]"` if you're working outside docker).
Expected: build succeeds, `channels-redis` and `fakeredis` install cleanly.

- [ ] **Step 1.5: Create the shared Redis client module**

Create `apps/common/redis_client.py`:

```python
"""One place to build the shared async Redis client for channels-redis-
adjacent state (presence hashes, turn-stop signals, presence last-seen
debounce). Uses redis.asyncio directly (the same library channels-redis
depends on) so we do not pull in a second Redis client dependency.

Module-level cache: the client owns its own connection pool. Re-creating
it per-call would leak sockets. A single cached instance per process is
fine for ASGI workers.
"""
from __future__ import annotations

import redis.asyncio as redis
from django.conf import settings

_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.asyncio.from_url(
            settings.ACE_REDIS_URL, decode_responses=True
        )
    return _client


async def close_redis() -> None:
    """Testing hook — close and reset the cached client."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
```

- [ ] **Step 1.6: Run the test — expect pass**

Run: `pytest apps/common/tests/test_redis_client.py -v`
Expected: PASS, 2 tests.

- [ ] **Step 1.7: Add Redis service to `docker-compose.yml`**

Modify `docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: ace
      POSTGRES_PASSWORD: ace
      POSTGRES_DB: ace_web
    ports:
      - "5434:5432"
    volumes:
      - ace-pg-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ace"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6380:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  app:
    build: .
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.development
      DJANGO_DEBUG: "True"
      DJANGO_SECRET_KEY: dev-insecure
      DATABASE_URL: postgres://ace:ace@db:5432/ace_web
      REDIS_URL: redis://redis:6379/0
      CONNECT_PRODUCTION_URL: ${CONNECT_PRODUCTION_URL:-https://connect.dimagi.com}
      CONNECT_OAUTH_CLIENT_ID: ${CONNECT_OAUTH_CLIENT_ID:-}
      CONNECT_OAUTH_CLIENT_SECRET: ${CONNECT_OAUTH_CLIENT_SECRET:-}
      FORCE_SCRIPT_NAME: ${FORCE_SCRIPT_NAME-/ace}
    ports:
      - "8000:8000"
    volumes:
      - ./apps:/app/apps
      - ./config:/app/config
      - ./manage.py:/app/manage.py
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy

  frontend:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    ports:
      - "3000:3000"
    depends_on:
      - app
    profiles: ["prod-parity"]

volumes:
  ace-pg-data:
```

- [ ] **Step 1.8: Verify `docker compose up` brings up Redis**

Run: `docker compose up -d redis && docker compose exec redis redis-cli ping`
Expected: `PONG`
Then: `docker compose down`

- [ ] **Step 1.9: Commit**

```bash
git add pyproject.toml docker-compose.yml apps/common/redis_client.py apps/common/tests/test_redis_client.py
git commit -m "feat(phase-3): add channels-redis, shared Redis client, dev Redis container"
```

---

## Task 2: Update settings for Redis-backed channel layer

**Files:**
- Modify: `config/settings/base.py`
- Modify: `config/settings/test.py`
- Modify: `config/settings/production.py`
- Modify: `config/settings/connectlabs.py`
- Create: `config/settings/tests/test_channels_layer.py` (smoke test that the layer class is what we expect)

- [ ] **Step 2.1: Write the failing test that asserts base settings use RedisChannelLayer**

Create `apps/common/tests/test_settings_channels.py`:

```python
"""Smoke tests that the channel-layer configuration is what we intend
for each settings module. These prevent silent regressions if someone
reinstates `InMemoryChannelLayer` on a production path."""
import importlib


def test_base_settings_use_redis_channel_layer(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    # Force a fresh import so env is read.
    import config.settings.base as base
    importlib.reload(base)
    assert base.CHANNEL_LAYERS["default"]["BACKEND"] == (
        "channels_redis.core.RedisChannelLayer"
    )
    hosts = base.CHANNEL_LAYERS["default"]["CONFIG"]["hosts"]
    assert hosts == ["redis://localhost:6379/0"]


def test_test_settings_override_back_to_inmemory():
    import config.settings.test as test_settings
    importlib.reload(test_settings)
    assert test_settings.CHANNEL_LAYERS["default"]["BACKEND"] == (
        "channels.layers.InMemoryChannelLayer"
    )
```

- [ ] **Step 2.2: Run the test — expect fail**

Run: `pytest apps/common/tests/test_settings_channels.py -v`
Expected: FAIL — base currently declares `InMemoryChannelLayer`.

- [ ] **Step 2.3: Update `config/settings/base.py`**

Modify the `--- Channels ---` block. Replace:

```python
# --- Channels ---
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}
```

with:

```python
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
```

- [ ] **Step 2.4: Update `config/settings/test.py`**

Replace the file contents with:

```python
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
```

- [ ] **Step 2.5: Update `config/settings/production.py`**

Strip the stale `WARNING: CHANNEL_LAYERS in base.py uses InMemoryChannelLayer` comment block. Replace lines 38–42 (the `# WARNING: …` block) with:

```python
# Channel layer is configured in base.py to use channels-redis pointing at
# REDIS_URL. connectlabs.py sources REDIS_URL from AWS Secrets Manager.
# See docs/learnings/channels-single-instance.md for the history.
```

- [ ] **Step 2.6: Update `config/settings/connectlabs.py`**

The file inherits `from .production import *` which now inherits the RedisChannelLayer from base. No channel-layer override is needed. Keep the file as-is but verify by reading it end-to-end — no changes should be required.

- [ ] **Step 2.7: Run the channel-layer smoke test**

Run: `pytest apps/common/tests/test_settings_channels.py -v`
Expected: PASS, 2 tests.

- [ ] **Step 2.8: Run the full test suite to confirm nothing else breaks**

Run: `pytest -x`
Expected: all previously-green tests still pass. `test_streaming.py` still passes at this stage — we have not touched it yet.

- [ ] **Step 2.9: Commit**

```bash
git add config/settings/base.py config/settings/test.py config/settings/production.py apps/common/tests/test_settings_channels.py
git commit -m "feat(phase-3): switch CHANNEL_LAYERS to channels-redis in base settings"
```

---

## Task 3: ASGI session-cookie auth middleware for WebSocket handshake

**Files:**
- Create: `apps/common/channels_auth.py`
- Create: `apps/common/tests/test_channels_auth.py`
- Modify: `config/asgi.py`

- [ ] **Step 3.1: Write the failing test**

Create `apps/common/tests/test_channels_auth.py`:

```python
"""Tests for AceSessionAuthMiddleware — the ASGI middleware that reads
the `sessionid_ace` cookie from a WebSocket handshake scope and resolves
it to a Django User.

These tests do not spin up a full ASGI server. They construct a fake
scope dict and call the middleware directly, asserting the attached
scope['user'] via an inner mock app that records the scope it received.
"""
from unittest.mock import AsyncMock

import pytest
from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore

from apps.common.channels_auth import AceSessionAuthMiddleware

pytestmark = pytest.mark.django_db


def _scope_with_cookies(cookies: dict[str, str]) -> dict:
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return {
        "type": "websocket",
        "path": "/ws/sessions/abc/",
        "headers": [(b"cookie", cookie_header.encode())],
    }


@pytest.fixture
def user():
    return get_user_model().objects.create_user(
        email="alice@dimagi.com", display_name="Alice"
    )


async def _run_middleware(scope):
    inner = AsyncMock()
    app = AceSessionAuthMiddleware(inner)
    await app(scope, AsyncMock(), AsyncMock())
    return inner.call_args.args[0]  # the scope passed to the inner app


async def test_missing_cookie_yields_anonymous_user():
    scope = _scope_with_cookies({})
    out = await _run_middleware(scope)
    assert isinstance(out["user"], AnonymousUser)


async def test_unknown_session_key_yields_anonymous_user():
    scope = _scope_with_cookies({settings.SESSION_COOKIE_NAME: "not-a-real-key"})
    out = await _run_middleware(scope)
    assert isinstance(out["user"], AnonymousUser)


async def test_valid_session_key_attaches_user(user):
    # Build a Django session row that references our user.
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    # Django auth also stores the backend path; AuthenticationMiddleware
    # uses it to reconstruct the user. We mirror it here.
    store["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    store["_auth_user_hash"] = user.get_session_auth_hash()
    store.save()

    scope = _scope_with_cookies({settings.SESSION_COOKIE_NAME: store.session_key})
    out = await _run_middleware(scope)
    assert out["user"].pk == user.pk
    assert out["user"].is_authenticated
```

- [ ] **Step 3.2: Run test — expect fail**

Run: `pytest apps/common/tests/test_channels_auth.py -v`
Expected: FAIL with ImportError on `apps.common.channels_auth`.

- [ ] **Step 3.3: Write the middleware**

Create `apps/common/channels_auth.py`:

```python
"""ASGI middleware that resolves `scope['user']` from a Django session
cookie on WebSocket handshake.

Channels ships its own `channels.auth.AuthMiddlewareStack` that does
something similar, but it hard-codes `settings.SESSION_COOKIE_NAME`
resolution through Django's session framework, which is fine — we
could use it directly. We define our own thin wrapper for two reasons:

1. Explicit control over the cookie-parsing step. The ace-web AWS
   deployment uses a tenant-specific cookie name (`sessionid_ace`) set
   in `connectlabs.py`. Wrapping the resolution in our own module makes
   that dependency visible and testable.
2. A single place to extend later (e.g., share-token fallbacks,
   per-session membership pre-checks before the consumer's connect()).

Usage (in config/asgi.py):

    application = ProtocolTypeRouter({
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AceSessionAuthMiddleware(URLRouter(websocket_urlpatterns))
        ),
    })
"""
from __future__ import annotations

from http.cookies import SimpleCookie

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore


def _parse_cookie_header(headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    """Parse the first `cookie` header from the ASGI scope into a dict."""
    for name, value in headers:
        if name == b"cookie":
            cookie = SimpleCookie()
            cookie.load(value.decode("latin-1"))
            return {k: morsel.value for k, morsel in cookie.items()}
    return {}


def _resolve_user_sync(session_key: str | None):
    """Resolve the session key to a User object (or AnonymousUser).

    Runs inside sync_to_async because it hits the DB.
    """
    if not session_key:
        return AnonymousUser()
    session = SessionStore(session_key=session_key)
    # A fake sync HttpRequest-ish shim that get_user() can introspect.
    # django.contrib.auth.get_user reads `request.session` and checks
    # `_auth_user_id` + `_auth_user_backend` + `_auth_user_hash`.
    class _Req:
        pass

    req = _Req()
    req.session = session
    user = get_user(req)
    return user


class AceSessionAuthMiddleware:
    """One-shot ASGI middleware. Attaches scope['user']."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        cookies = _parse_cookie_header(scope.get("headers", []))
        session_key = cookies.get(settings.SESSION_COOKIE_NAME)
        user = await sync_to_async(_resolve_user_sync)(session_key)
        # Copy the scope so we do not mutate the caller's dict.
        scope = {**scope, "user": user}
        return await self.inner(scope, receive, send)
```

- [ ] **Step 3.4: Run test — expect pass**

Run: `pytest apps/common/tests/test_channels_auth.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 3.5: Wire the middleware into `config/asgi.py`**

Replace `config/asgi.py` with:

```python
"""ASGI entry point with Channels routing."""
import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

# Defaults to production because uvicorn/daphne are the production entry
# points. Local dev overrides this via DJANGO_SETTINGS_MODULE in
# docker-compose or the shell.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

django_asgi_app = get_asgi_application()

from apps.common.channels_auth import AceSessionAuthMiddleware  # noqa: E402
from apps.sessions.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AceSessionAuthMiddleware(URLRouter(websocket_urlpatterns))
        ),
    }
)
```

- [ ] **Step 3.6: Run the existing ASGI smoke test**

Run: `pytest tests/test_asgi.py -v` (or `pytest tests/` if the smoke test lives there — check what exists)
Expected: PASS.

- [ ] **Step 3.7: Commit**

```bash
git add apps/common/channels_auth.py apps/common/tests/test_channels_auth.py config/asgi.py
git commit -m "feat(phase-3): ASGI session-cookie auth middleware for WebSocket handshake"
```

---

## Task 4: Presence module (Redis HASH + debounced last_seen write)

**Files:**
- Create: `apps/sessions/presence.py`
- Create: `apps/sessions/tests/test_presence.py`

- [ ] **Step 4.1: Write the failing tests**

Create `apps/sessions/tests/test_presence.py`:

```python
"""Unit tests for the Redis-backed presence module. Uses fakeredis as a
drop-in for redis.asyncio.Redis."""
import time
from unittest.mock import patch

import fakeredis.aioredis
import pytest

from apps.sessions import presence
from apps.sessions.models import Session, SessionParticipant

pytestmark = pytest.mark.django_db


@pytest.fixture
async def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        "apps.common.redis_client.get_redis",
        lambda: _awaitable(client),
    )
    yield client
    await client.flushall()
    await client.aclose()


def _awaitable(value):
    async def _inner():
        return value
    return _inner()


@pytest.fixture
def session(django_user_model):
    user = django_user_model.objects.create_user(
        email="alice@dimagi.com", display_name="Alice"
    )
    session = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=session, user=user, role="owner")
    return session


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(
        email="bob@dimagi.com", display_name="Bob"
    )


async def test_touch_adds_user_to_hash(fake_redis, session):
    was_new = await presence.touch(session.slug, session.owner.id)
    assert was_new is True
    members = await fake_redis.hkeys(f"presence:{session.slug}")
    assert str(session.owner.id) in members


async def test_touch_repeat_returns_was_new_false(fake_redis, session):
    await presence.touch(session.slug, session.owner.id)
    was_new = await presence.touch(session.slug, session.owner.id)
    assert was_new is False


async def test_snapshot_returns_current_user_ids(fake_redis, session, other_user):
    await presence.touch(session.slug, session.owner.id)
    await presence.touch(session.slug, other_user.id)
    ids = await presence.snapshot(session.slug)
    assert set(ids) == {session.owner.id, other_user.id}


async def test_snapshot_drops_expired_entries(fake_redis, session):
    # Manually insert an expired field — simulate a crashed client whose
    # TTL has passed.
    await fake_redis.hset(
        f"presence:{session.slug}",
        str(session.owner.id),
        str(int(time.time()) - 10),
    )
    ids = await presence.snapshot(session.slug)
    assert ids == []
    remaining = await fake_redis.hkeys(f"presence:{session.slug}")
    assert remaining == []  # Lazy sweep removed it.


async def test_leave_removes_user(fake_redis, session):
    await presence.touch(session.slug, session.owner.id)
    await presence.leave(session.slug, session.owner.id)
    ids = await presence.snapshot(session.slug)
    assert ids == []


async def test_is_present_checks_both_existence_and_expiry(fake_redis, session):
    await presence.touch(session.slug, session.owner.id)
    assert await presence.is_present(session.slug, session.owner.id)
    await presence.leave(session.slug, session.owner.id)
    assert not await presence.is_present(session.slug, session.owner.id)


async def test_maybe_record_last_seen_debounces_writes(
    fake_redis, session, other_user
):
    SessionParticipant.objects.create(
        session=session, user=other_user, role="editor"
    )
    wrote_first = await presence.maybe_record_last_seen(
        session.slug, other_user.id, session_pk=session.pk
    )
    wrote_second = await presence.maybe_record_last_seen(
        session.slug, other_user.id, session_pk=session.pk
    )
    assert wrote_first is True
    assert wrote_second is False
    row = SessionParticipant.objects.get(session=session, user=other_user)
    assert row.last_seen_at is not None
```

- [ ] **Step 4.2: Run tests — expect fail**

Run: `pytest apps/sessions/tests/test_presence.py -v`
Expected: FAIL with import errors on `apps.sessions.presence`.

- [ ] **Step 4.3: Write the presence module**

Create `apps/sessions/presence.py`:

```python
"""Redis-backed presence for multi-player sessions.

Data layout:

  presence:{session_slug}             HASH
      field: str(user_id)             value: str(expires_at_epoch_seconds)

  presence.last_seen:{slug}:{user_id} STRING (30s TTL)
      presence-only; the existence of the key means "we already wrote
      SessionParticipant.last_seen_at within the last 30s for this
      (slug, user) pair; skip the DB write."

Why a HASH with per-field expires rather than Redis key TTLs:
- One key per session → O(1) connect/disconnect even with many sessions.
- No per-user key explosion.
- Lazy sweep on read is sufficient for our scale (a few team members per
  session at most).

The debounced last_seen_at write is a SETNX on a 30s TTL key. Atomic
across ECS tasks so only one of them writes the DB row even if two
consumers on different tasks receive a heartbeat for the same user in
the same ~30s window.
"""
from __future__ import annotations

import time

from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.common.redis_client import get_redis

from .models import SessionParticipant

PRESENCE_TTL_SECONDS = 60
LAST_SEEN_DEBOUNCE_SECONDS = 30


def _hash_key(session_slug: str) -> str:
    return f"presence:{session_slug}"


def _last_seen_key(session_slug: str, user_id: int) -> str:
    return f"presence.last_seen:{session_slug}:{user_id}"


async def touch(session_slug: str, user_id: int) -> bool:
    """Refresh this user's presence entry for this session.

    Returns True if the user was not present before this call (the field
    was newly added), False if they were already present.
    """
    r = await get_redis()
    key = _hash_key(session_slug)
    expires_at = int(time.time()) + PRESENCE_TTL_SECONDS
    # HSET returns the number of fields created — 1 for new, 0 for update.
    created = await r.hset(key, str(user_id), str(expires_at))
    return bool(created)


async def leave(session_slug: str, user_id: int) -> None:
    r = await get_redis()
    await r.hdel(_hash_key(session_slug), str(user_id))


async def snapshot(session_slug: str) -> list[int]:
    """Return currently-present user_ids for this session.

    Lazily sweeps expired fields while it is reading the hash. O(n) in
    the number of fields per session — fine for our expected size.
    """
    r = await get_redis()
    key = _hash_key(session_slug)
    raw = await r.hgetall(key)
    now = int(time.time())
    alive: list[int] = []
    expired: list[str] = []
    for field, value in raw.items():
        try:
            if int(value) > now:
                alive.append(int(field))
            else:
                expired.append(field)
        except (TypeError, ValueError):
            expired.append(field)
    if expired:
        await r.hdel(key, *expired)
    return alive


async def is_present(session_slug: str, user_id: int) -> bool:
    r = await get_redis()
    value = await r.hget(_hash_key(session_slug), str(user_id))
    if value is None:
        return False
    try:
        return int(value) > int(time.time())
    except (TypeError, ValueError):
        return False


async def maybe_record_last_seen(
    session_slug: str, user_id: int, *, session_pk: int
) -> bool:
    """Debounced write of SessionParticipant.last_seen_at.

    Returns True if this call wrote to the DB, False if skipped (a
    recent write is still within the debounce TTL).
    """
    r = await get_redis()
    key = _last_seen_key(session_slug, user_id)
    # SET NX EX — succeeds only if the key does not already exist.
    acquired = await r.set(key, "1", ex=LAST_SEEN_DEBOUNCE_SECONDS, nx=True)
    if not acquired:
        return False
    await sync_to_async(_write_last_seen)(session_pk, user_id)
    return True


def _write_last_seen(session_pk: int, user_id: int) -> None:
    SessionParticipant.objects.filter(
        session_id=session_pk, user_id=user_id
    ).update(last_seen_at=timezone.now())
```

- [ ] **Step 4.4: Run tests — expect pass**

Run: `pytest apps/sessions/tests/test_presence.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 4.5: Commit**

```bash
git add apps/sessions/presence.py apps/sessions/tests/test_presence.py
git commit -m "feat(phase-3): Redis HASH presence with debounced last_seen writer"
```

---

## Task 5: Drafts state machine

**Files:**
- Create: `apps/sessions/drafts.py`
- Create: `apps/sessions/tests/test_drafts.py`

- [ ] **Step 5.1: Write the failing tests**

Create `apps/sessions/tests/test_drafts.py`:

```python
"""Unit tests for the draft state machine. Each helper is a sync DB
operation — no WebSocket, no Redis."""
import time

import pytest

from apps.sessions import drafts
from apps.sessions.models import Draft, Message, Session, SessionParticipant

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        email="alice@dimagi.com", display_name="Alice"
    )


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(
        email="bob@dimagi.com", display_name="Bob"
    )


@pytest.fixture
def session(alice, bob):
    s = Session.objects.create(owner=alice, title="x")
    SessionParticipant.objects.create(session=s, user=alice, role="owner")
    SessionParticipant.objects.create(session=s, user=bob, role="editor")
    return s


def test_get_or_create_active_draft_creates_empty(session, alice):
    draft = drafts.get_or_create_active_draft(session, alice)
    assert draft.slot == "next"
    assert draft.status == "open"
    assert draft.body == ""
    assert draft.version == 0
    assert draft.last_editor_id == alice.id


def test_get_or_create_active_draft_returns_existing(session, alice):
    first = drafts.get_or_create_active_draft(session, alice)
    second = drafts.get_or_create_active_draft(session, alice)
    assert first.pk == second.pk


def test_update_body_bumps_version_and_last_editor(session, alice, bob):
    draft = drafts.get_or_create_active_draft(session, alice)
    updated = drafts.update_body(
        draft_id=draft.pk, user=bob, expected_version=0, new_body="hello"
    )
    assert updated.version == 1
    assert updated.body == "hello"
    assert updated.last_editor_id == bob.id


def test_update_body_raises_on_stale_version(session, alice):
    draft = drafts.get_or_create_active_draft(session, alice)
    drafts.update_body(
        draft_id=draft.pk, user=alice, expected_version=0, new_body="hi"
    )
    with pytest.raises(drafts.DraftVersionMismatch) as exc_info:
        drafts.update_body(
            draft_id=draft.pk,
            user=alice,
            expected_version=0,
            new_body="wrong",
        )
    assert exc_info.value.current_version == 1
    assert exc_info.value.current_body == "hi"


def test_claim_lock_succeeds_when_idle(session, alice, bob):
    draft = drafts.get_or_create_active_draft(session, alice)
    # Backdate updated_at to simulate 10s idle.
    Draft.objects.filter(pk=draft.pk).update(
        updated_at=_ten_seconds_ago()
    )
    result = drafts.claim_lock(
        draft_id=draft.pk, user=bob, holder_is_present=True
    )
    assert result.last_editor_id == bob.id


def test_claim_lock_succeeds_when_holder_absent(session, alice, bob):
    draft = drafts.get_or_create_active_draft(session, alice)
    # Draft was just updated but holder has disconnected.
    result = drafts.claim_lock(
        draft_id=draft.pk, user=bob, holder_is_present=False
    )
    assert result.last_editor_id == bob.id


def test_claim_lock_fails_when_holder_active(session, alice, bob):
    draft = drafts.get_or_create_active_draft(session, alice)
    with pytest.raises(drafts.DraftLockHeld) as exc_info:
        drafts.claim_lock(
            draft_id=draft.pk, user=bob, holder_is_present=True
        )
    assert exc_info.value.holder_user_id == alice.id


def test_commit_creates_user_message_assistant_placeholder_and_new_draft(
    session, alice
):
    draft = drafts.get_or_create_active_draft(session, alice)
    drafts.update_body(
        draft_id=draft.pk, user=alice, expected_version=0, new_body="hello"
    )
    result = drafts.commit_active_draft(session=session, user=alice)

    user_msg = Message.objects.get(pk=result.user_message_id)
    asst_msg = Message.objects.get(pk=result.assistant_message_id)
    assert user_msg.role == "user"
    assert user_msg.plaintext == "hello"
    assert user_msg.status == "complete"
    assert asst_msg.role == "assistant"
    assert asst_msg.status == "pending"
    assert asst_msg.turn_index == user_msg.turn_index + 1

    old = Draft.objects.get(pk=draft.pk)
    assert old.status == "sent"
    assert old.sent_message_id == asst_msg.id

    new_draft = Draft.objects.get(pk=result.new_draft_id)
    assert new_draft.status == "open"
    assert new_draft.slot == "next"
    assert new_draft.body == ""
    assert new_draft.version == 0


def test_commit_is_noop_when_body_is_empty(session, alice):
    drafts.get_or_create_active_draft(session, alice)
    result = drafts.commit_active_draft(session=session, user=alice)
    assert result is None
    assert Message.objects.filter(session=session).count() == 0


def test_discard_resets_body_and_bumps_version(session, alice):
    draft = drafts.get_or_create_active_draft(session, alice)
    drafts.update_body(
        draft_id=draft.pk, user=alice, expected_version=0, new_body="oops"
    )
    cleared = drafts.discard(draft_id=draft.pk, user=alice)
    assert cleared.body == ""
    assert cleared.version == 2  # +1 for update, +1 for discard
    assert cleared.status == "open"


def _ten_seconds_ago():
    from django.utils import timezone as tz
    from datetime import timedelta
    return tz.now() - timedelta(seconds=10)
```

- [ ] **Step 5.2: Run tests — expect fail**

Run: `pytest apps/sessions/tests/test_drafts.py -v`
Expected: FAIL on `apps.sessions.drafts` import.

- [ ] **Step 5.3: Write the drafts module**

Create `apps/sessions/drafts.py`:

```python
"""Draft state machine for Phase 3 multi-player collaboration.

All operations are synchronous Django ORM. The WebSocket consumer wraps
them in `sync_to_async` calls. Keeping this module sync-only simplifies
testing (no pytest-asyncio gymnastics) and lets us reuse Django's
transaction + select_for_update primitives directly.

The soft lock is derived, not stored — there is no separate lock table.
The "holder" is Draft.last_editor; the lock is idle when
    now() - Draft.updated_at > LOCK_IDLE_SECONDS
OR the holder is not present in the session (checked by the caller via
apps.sessions.presence.is_present, passed in as `holder_is_present`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Draft, Message, Session

LOCK_IDLE_SECONDS = 2


class DraftVersionMismatch(Exception):
    """Raised when an update carries a stale version."""

    def __init__(self, current_version: int, current_body: str) -> None:
        self.current_version = current_version
        self.current_body = current_body
        super().__init__(
            f"stale version; current is {current_version}"
        )


class DraftLockHeld(Exception):
    """Raised when take_over is attempted against a live lock."""

    def __init__(self, holder_user_id: int, expires_at: float) -> None:
        self.holder_user_id = holder_user_id
        self.expires_at = expires_at
        super().__init__(
            f"lock held by user {holder_user_id} until {expires_at}"
        )


@dataclass
class CommitResult:
    user_message_id: int
    assistant_message_id: int
    old_draft_id: int
    new_draft_id: int


def get_or_create_active_draft(session: Session, user) -> Draft:
    """Return the open slot='next' draft for this session, creating one
    if none exists. `user` is used as creator/last_editor on creation.

    Serializes concurrent callers via a row-lock on the session row so
    two simultaneous connects cannot both try to create a draft and
    violate the one_next_per_session partial unique constraint.
    """
    with transaction.atomic():
        locked_session = Session.objects.select_for_update().get(pk=session.pk)
        draft = (
            Draft.objects.filter(
                session=locked_session, slot="next", status="open"
            ).first()
        )
        if draft is not None:
            return draft
        return Draft.objects.create(
            session=locked_session,
            slot="next",
            status="open",
            body="",
            version=0,
            creator_user=user,
            last_editor=user,
        )


def update_body(
    *, draft_id: int, user, expected_version: int, new_body: str
) -> Draft:
    """Apply an update from a user's client. Version-guarded.

    Raises DraftVersionMismatch if expected_version does not match the
    current row version.
    """
    with transaction.atomic():
        draft = Draft.objects.select_for_update().get(pk=draft_id)
        if draft.version != expected_version:
            raise DraftVersionMismatch(
                current_version=draft.version, current_body=draft.body
            )
        draft.body = new_body
        draft.version += 1
        draft.last_editor = user
        draft.save(update_fields=["body", "version", "last_editor", "updated_at"])
        return draft


def claim_lock(*, draft_id: int, user, holder_is_present: bool) -> Draft:
    """Transfer the soft lock to `user`. Allowed if the lock is idle or
    the current holder is not in the presence set.

    Raises DraftLockHeld otherwise.
    """
    with transaction.atomic():
        draft = Draft.objects.select_for_update().get(pk=draft_id)
        idle_cutoff = timezone.now() - timedelta(seconds=LOCK_IDLE_SECONDS)
        is_idle = draft.updated_at < idle_cutoff
        if not is_idle and holder_is_present:
            expires_at = (
                draft.updated_at + timedelta(seconds=LOCK_IDLE_SECONDS)
            ).timestamp()
            raise DraftLockHeld(
                holder_user_id=draft.last_editor_id,
                expires_at=expires_at,
            )
        draft.last_editor = user
        draft.save(update_fields=["last_editor", "updated_at"])
        return draft


def discard(*, draft_id: int, user) -> Draft:
    """Clear the body. Keeps slot='next', status='open', bumps version."""
    with transaction.atomic():
        draft = Draft.objects.select_for_update().get(pk=draft_id)
        draft.body = ""
        draft.version += 1
        draft.last_editor = user
        draft.save(update_fields=["body", "version", "last_editor", "updated_at"])
        return draft


def commit_active_draft(*, session: Session, user) -> CommitResult | None:
    """Commit the active draft as a user Message, create the assistant
    placeholder, open a fresh next-draft. Idempotent guard: returns None
    if no open draft exists OR the draft body is empty.
    """
    with transaction.atomic():
        locked_session = Session.objects.select_for_update().get(pk=session.pk)
        draft = (
            Draft.objects.select_for_update()
            .filter(session=locked_session, slot="next", status="open")
            .first()
        )
        if draft is None or not draft.body.strip():
            return None

        body = draft.body

        last_turn = (
            Message.objects.filter(session=locked_session)
            .order_by("-turn_index")
            .values_list("turn_index", flat=True)
            .first()
        )
        next_turn = (last_turn or 0) + 1

        user_msg = Message.objects.create(
            session=locked_session,
            turn_index=next_turn,
            role="user",
            sender_user=user,
            content={"text": body},
            plaintext=body,
            status="complete",
            completed_at=timezone.now(),
        )
        assistant_msg = Message.objects.create(
            session=locked_session,
            turn_index=next_turn + 1,
            role="assistant",
            content={"text": ""},
            plaintext="",
            status="pending",
        )

        draft.status = "sent"
        draft.sent_message = assistant_msg
        draft.sent_at = timezone.now()
        draft.save(update_fields=["status", "sent_message", "sent_at", "updated_at"])

        new_draft = Draft.objects.create(
            session=locked_session,
            slot="next",
            status="open",
            body="",
            version=0,
            creator_user=user,
            last_editor=user,
        )

        return CommitResult(
            user_message_id=user_msg.id,
            assistant_message_id=assistant_msg.id,
            old_draft_id=draft.id,
            new_draft_id=new_draft.id,
        )
```

- [ ] **Step 5.4: Run tests — expect pass**

Run: `pytest apps/sessions/tests/test_drafts.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 5.5: Commit**

```bash
git add apps/sessions/drafts.py apps/sessions/tests/test_drafts.py
git commit -m "feat(phase-3): draft state machine with version-guarded update and soft-lock claim"
```

---

## Task 6: Turn driver (extract from streaming.py)

**Files:**
- Create: `apps/sessions/turn_driver.py`
- Create: `apps/sessions/tests/test_turn_driver.py`

- [ ] **Step 6.1: Write the failing tests**

Create `apps/sessions/tests/test_turn_driver.py`:

```python
"""Tests for apps.sessions.turn_driver.drive_assistant_turn.

Stubs ChatBackend with a scripted StreamEvent sequence and asserts both
the events yielded by drive_assistant_turn AND the final DB state of
the Message row.
"""
import asyncio
from unittest.mock import patch

import pytest

from apps.common.chat_backend import StreamEvent, StreamEventType
from apps.sessions import turn_driver
from apps.sessions.models import Message, Session, SessionParticipant

pytestmark = pytest.mark.django_db


@pytest.fixture
def session(django_user_model):
    user = django_user_model.objects.create_user(
        email="alice@dimagi.com", display_name="Alice"
    )
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    return s


@pytest.fixture
def user_and_assistant_messages(session):
    user_msg = Message.objects.create(
        session=session, turn_index=1, role="user",
        content={"text": "hi"}, plaintext="hi", status="complete",
    )
    asst_msg = Message.objects.create(
        session=session, turn_index=2, role="assistant",
        content={"text": ""}, plaintext="", status="pending",
    )
    return user_msg, asst_msg


class FakeBackend:
    def __init__(self, events):
        self._events = events

    async def stream_completion(self, *, session, new_user_message, **kwargs):
        for e in self._events:
            yield e


async def _drain(agen):
    out = []
    async for item in agen:
        out.append(item)
    return out


async def test_happy_path_marks_complete_and_yields_events(
    session, user_and_assistant_messages
):
    _user, asst = user_and_assistant_messages
    events = [
        StreamEvent.delta(text="Hel"),
        StreamEvent.delta(text="lo"),
        StreamEvent.done(),
    ]
    stop_event = asyncio.Event()
    with patch("apps.sessions.turn_driver._get_backend", return_value=FakeBackend(events)):
        yielded = await _drain(
            turn_driver.drive_assistant_turn(
                assistant_message_id=asst.id, stop_event=stop_event
            )
        )

    # Backend events pass through 1:1 (plus maybe an implicit DONE dedup).
    assert any(e.type is StreamEventType.DELTA and e.text == "Hel" for e in yielded)
    assert any(e.type is StreamEventType.DELTA and e.text == "lo" for e in yielded)

    refreshed = Message.objects.get(pk=asst.id)
    assert refreshed.status == "complete"
    assert refreshed.plaintext == "Hello"


async def test_tool_use_creates_nested_message_row(
    session, user_and_assistant_messages
):
    _user, asst = user_and_assistant_messages
    events = [
        StreamEvent.delta(text="Let me search."),
        StreamEvent.tool_use(block={"name": "Grep", "id": "tool-1"}),
        StreamEvent.tool_result(block={"tool_use_id": "tool-1", "content": "ok"}),
        StreamEvent.done(),
    ]
    stop_event = asyncio.Event()
    with patch("apps.sessions.turn_driver._get_backend", return_value=FakeBackend(events)):
        await _drain(
            turn_driver.drive_assistant_turn(
                assistant_message_id=asst.id, stop_event=stop_event
            )
        )

    rows = list(Message.objects.filter(session=session).order_by("turn_index"))
    roles = [r.role for r in rows]
    assert "tool_use" in roles
    assert "tool_result" in roles


async def test_error_event_marks_message_error(
    session, user_and_assistant_messages
):
    _user, asst = user_and_assistant_messages
    events = [StreamEvent.for_error(message="boom")]
    stop_event = asyncio.Event()
    with patch("apps.sessions.turn_driver._get_backend", return_value=FakeBackend(events)):
        await _drain(
            turn_driver.drive_assistant_turn(
                assistant_message_id=asst.id, stop_event=stop_event
            )
        )

    refreshed = Message.objects.get(pk=asst.id)
    assert refreshed.status == "error"
    assert "boom" in refreshed.error_detail


async def test_stop_event_cancels_mid_stream(
    session, user_and_assistant_messages
):
    _user, asst = user_and_assistant_messages

    class SlowBackend:
        async def stream_completion(self, **kwargs):
            yield StreamEvent.delta(text="partial ")
            # Block forever; the stop_event should pull the plug.
            await asyncio.sleep(3600)
            yield StreamEvent.done()

    stop_event = asyncio.Event()

    async def run_and_stop():
        agen = turn_driver.drive_assistant_turn(
            assistant_message_id=asst.id, stop_event=stop_event
        )
        collected = []
        async for event in agen:
            collected.append(event)
            stop_event.set()
        return collected

    with patch("apps.sessions.turn_driver._get_backend", return_value=SlowBackend()):
        await asyncio.wait_for(run_and_stop(), timeout=5)

    refreshed = Message.objects.get(pk=asst.id)
    assert refreshed.status == "error"
    assert "cancelled" in refreshed.error_detail
```

- [ ] **Step 6.2: Run tests — expect fail**

Run: `pytest apps/sessions/tests/test_turn_driver.py -v`
Expected: FAIL on `apps.sessions.turn_driver` import.

- [ ] **Step 6.3: Write the turn driver module**

Create `apps/sessions/turn_driver.py`:

```python
"""Drive one assistant turn end-to-end: kick off CLIBackend.stream_completion,
debounce plaintext updates to the Message row, create tool_use / tool_result
child rows, and propagate DONE / ERROR / CANCELLED terminal states.

This module is the Phase 3 replacement for the SSE generator in
apps.sessions.streaming. The SSE framing (`event: delta\\ndata: {...}`)
is gone; instead we yield raw StreamEvent objects so the consumer can
broadcast them to the Channels group however it wants.

Cancellation: the caller passes an asyncio.Event. The driver checks it
before each backend yield. When set, the backend's async generator is
closed (which triggers its finally block — SIGTERM → SIGKILL in
CLIBackend), the Message row is marked error with partial-length detail,
and drive_assistant_turn yields a single error event before returning.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from apps.common.chat_backend import StreamEvent, StreamEventType
from apps.common.cli_backend import CLIBackend, CLIBackendError

from .models import Message, Session

logger = logging.getLogger(__name__)

# Module-level singleton CLIBackend. Keep as a function so tests can patch it.
_backend: CLIBackend | None = None


def _get_backend() -> CLIBackend:
    global _backend
    if _backend is None:
        _backend = CLIBackend()
    return _backend


async def drive_assistant_turn(
    *, assistant_message_id: int, stop_event: asyncio.Event
) -> AsyncIterator[StreamEvent]:
    """Drive a single assistant turn. Yields StreamEvents to the caller.

    The caller is responsible for broadcasting events to any listening
    WebSocket group. This module just owns the backend + DB state
    machine.
    """
    message = await sync_to_async(_load_message)(assistant_message_id)
    if message is None:
        yield StreamEvent.for_error(message="assistant message not found")
        return

    # Handle reconnect-on-replay: if the message is already finished,
    # yield the replay once and stop. This mirrors the Phase 2 SSE
    # behavior and ensures that `session.state` + any late join lands
    # at a consistent cursor.
    if message.status in ("complete", "streaming"):
        if message.plaintext:
            yield StreamEvent.delta(text=message.plaintext)
        yield StreamEvent.done()
        return
    if message.status == "error":
        yield StreamEvent.for_error(message=message.error_detail or "unknown")
        return

    user_text = await sync_to_async(_load_last_user_text)(message)
    backend = _get_backend()
    await sync_to_async(_mark_streaming)(message)

    accumulated: list[str] = []
    last_db_write = asyncio.get_running_loop().time()

    try:
        agen = backend.stream_completion(
            session=message.session, new_user_message=user_text
        )
        try:
            async for event in agen:
                if stop_event.is_set():
                    break

                yield event

                if event.type is StreamEventType.DELTA and event.text:
                    accumulated.append(event.text)
                    now = asyncio.get_running_loop().time()
                    if now - last_db_write > 0.25:
                        await sync_to_async(_update_plaintext)(
                            message, "".join(accumulated)
                        )
                        last_db_write = now

                elif event.type is StreamEventType.TOOL_USE:
                    await sync_to_async(_create_tool_message)(
                        message.session, event.tool_block, role="tool_use"
                    )

                elif event.type is StreamEventType.TOOL_RESULT:
                    await sync_to_async(_create_tool_message)(
                        message.session, event.tool_block, role="tool_result"
                    )

                elif event.type is StreamEventType.DONE:
                    await sync_to_async(_mark_complete)(
                        message, "".join(accumulated)
                    )
                    _schedule_auto_title(message.session)
                    return

                elif event.type is StreamEventType.ERROR:
                    await sync_to_async(_mark_error)(
                        message, event.error or "unknown"
                    )
                    return
        finally:
            # Closes the subprocess (SIGTERM → SIGKILL in CLIBackend).
            await agen.aclose()

        if stop_event.is_set():
            partial = "".join(accumulated)
            await sync_to_async(_mark_error)(
                message, f"cancelled (partial: {len(partial)} chars)"
            )
            yield StreamEvent.for_error(message="cancelled")
            return

        # Loop exited cleanly without DONE/ERROR — mark complete with what we have.
        await sync_to_async(_mark_complete)(message, "".join(accumulated))
        _schedule_auto_title(message.session)

    except CLIBackendError as exc:
        logger.exception("CLIBackend failed during assistant turn")
        await sync_to_async(_mark_error)(message, str(exc))
        yield StreamEvent.for_error(message=str(exc))

    except asyncio.CancelledError:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.shield(
                sync_to_async(_mark_error)(
                    message,
                    f"cancelled (partial: {len(''.join(accumulated))} chars)",
                )
            )
        raise


def _schedule_auto_title(session: Session) -> None:
    """Fire-and-forget auto-title. Swallows exceptions.

    Same behavior as Phase 2; lifted verbatim from streaming.py.
    """
    from .auto_title import generate_title_for_session

    async def _runner():
        try:
            await generate_title_for_session(session)
        except Exception:
            logger.exception("Auto-title task failed for session %s", session.slug)

    asyncio.create_task(_runner())


# ────────────────────────────── DB helpers ──────────────────────────────
# These are lifted from apps/sessions/streaming.py. When that file is
# deleted in Task 7, these become the sole implementations.

def _load_message(message_id: int) -> Message | None:
    try:
        return Message.objects.select_related("session").get(pk=message_id)
    except Message.DoesNotExist:
        return None


def _load_last_user_text(asst_message: Message) -> str:
    user_msg = (
        Message.objects.filter(
            session=asst_message.session,
            role="user",
            turn_index__lt=asst_message.turn_index,
        )
        .order_by("-turn_index")
        .first()
    )
    return user_msg.plaintext if user_msg else ""


def _mark_streaming(message: Message) -> None:
    Message.objects.filter(pk=message.pk).update(
        status="streaming", started_at=timezone.now()
    )


def _update_plaintext(message: Message, text: str) -> None:
    Message.objects.filter(pk=message.pk).update(plaintext=text)


def _mark_complete(message: Message, text: str) -> None:
    Message.objects.filter(pk=message.pk).update(
        status="complete",
        plaintext=text,
        content={"text": text},
        completed_at=timezone.now(),
    )


def _mark_error(message: Message, detail: str) -> None:
    Message.objects.filter(pk=message.pk).update(
        status="error",
        error_detail=detail,
        completed_at=timezone.now(),
    )


def _summarize_tool_block(block: dict) -> str:
    if "name" in block:
        return str(block.get("name", ""))
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return ""


def _create_tool_message(session: Session, block: dict, *, role: str) -> None:
    with transaction.atomic():
        locked_session = Session.objects.select_for_update().get(pk=session.pk)
        last_turn = (
            Message.objects.filter(session=locked_session)
            .order_by("-turn_index")
            .values_list("turn_index", flat=True)
            .first()
        )
        Message.objects.create(
            session=locked_session,
            turn_index=(last_turn or 0) + 1,
            role=role,
            content=block,
            plaintext=_summarize_tool_block(block),
            status="complete",
            completed_at=timezone.now(),
        )
```

- [ ] **Step 6.4: Run tests — expect pass**

Run: `pytest apps/sessions/tests/test_turn_driver.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 6.5: Commit**

```bash
git add apps/sessions/turn_driver.py apps/sessions/tests/test_turn_driver.py
git commit -m "feat(phase-3): turn_driver — assistant stream loop lifted from SSE view"
```

---

## Task 7: Delete SSE streaming view and its tests

**Files:**
- Delete: `apps/sessions/streaming.py`
- Delete: `apps/sessions/tests/test_streaming.py`
- Modify: `apps/sessions/urls.py` (drop the `message_stream` route)

- [ ] **Step 7.1: Delete the files**

```bash
git rm apps/sessions/streaming.py apps/sessions/tests/test_streaming.py
```

- [ ] **Step 7.2: Update `apps/sessions/urls.py`**

Replace the file contents with:

```python
from django.urls import path

from . import views

urlpatterns = [
    path("sessions", views.session_collection, name="session_collection"),
    path("sessions/<slug:slug>", views.session_detail, name="session_detail"),
    path(
        "sessions/<slug:slug>/messages",
        views.messages_list,
        name="messages_list",
    ),
    path(
        "sessions/<slug:slug>/participants",
        views.participant_collection,
        name="participant_collection",
    ),
]
```

(The `send_message` and `message_stream` routes are gone. `messages_list` and `participant_collection` are added in Task 8; importing them now gives ImportError — that is expected and will resolve at Task 8 time.)

- [ ] **Step 7.3: Skip running tests here**

Because `urls.py` now references views that don't exist yet, the whole test suite will fail to import until Task 8 is complete. That's OK — Task 8 is the immediate next step and both commits land together on the same branch. Do not run `pytest` between Task 7 and Task 8.

- [ ] **Step 7.4: Commit**

```bash
git add apps/sessions/streaming.py apps/sessions/tests/test_streaming.py apps/sessions/urls.py
git commit -m "refactor(phase-3): delete SSE streaming view and test (superseded by turn_driver)"
```

---

## Task 8: REST surface changes — messages GET, participant add, send_message delete

**Files:**
- Modify: `apps/sessions/views.py`
- Modify: `apps/sessions/serializers.py`
- Modify: `apps/sessions/tests/test_views.py`

- [ ] **Step 8.1: Write the failing tests for the new view endpoints**

Replace `apps/sessions/tests/test_views.py` with:

```python
import pytest
from rest_framework.test import APIClient

from apps.sessions.models import Message, Session, SessionParticipant

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="alice@dimagi.com", display_name="Alice"
    )


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(
        email="bob@dimagi.com", display_name="Bob"
    )


@pytest.fixture
def non_dimagi_user(django_user_model):
    return django_user_model.objects.create_user(
        email="evil@example.com", display_name="Evil"
    )


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_create_session_returns_slug(client):
    resp = client.post("/api/sessions", {}, format="json")
    assert resp.status_code == 201
    body = resp.json()
    assert body["error"] is None
    assert "slug" in body["data"]
    assert body["data"]["status"] == "active"


def test_create_session_creates_owner_participant(client, user):
    resp = client.post("/api/sessions", {}, format="json")
    slug = resp.json()["data"]["slug"]
    s = Session.objects.get(slug=slug)
    assert s.participants.filter(user=user, role="owner").exists()


def test_list_sessions_only_returns_current_user(client, user, other_user):
    Session.objects.create(owner=user, title="mine")
    Session.objects.create(owner=other_user, title="theirs")

    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    titles = [s["title"] for s in resp.json()["data"]]
    assert "mine" in titles
    assert "theirs" not in titles


def test_list_sessions_filters_by_status(client, user):
    Session.objects.create(owner=user, title="active")
    Session.objects.create(owner=user, title="archived", status="archived")

    resp = client.get("/api/sessions?status=archived")
    titles = [s["title"] for s in resp.json()["data"]]
    assert titles == ["archived"]


def test_get_session_by_slug(client, user):
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    resp = client.get(f"/api/sessions/{s.slug}")
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "x"
    assert resp.json()["data"]["messages"] == []


def test_patch_session_title(client, user):
    s = Session.objects.create(owner=user, title="old")
    resp = client.patch(
        f"/api/sessions/{s.slug}",
        {"title": "new"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "new"


def test_messages_list_returns_ordered_messages(client, user):
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    Message.objects.create(
        session=s, turn_index=1, role="user",
        content={"text": "hi"}, plaintext="hi", status="complete",
    )
    Message.objects.create(
        session=s, turn_index=2, role="assistant",
        content={"text": "hello"}, plaintext="hello", status="complete",
    )
    resp = client.get(f"/api/sessions/{s.slug}/messages")
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert [r["turn_index"] for r in rows] == [1, 2]


def test_messages_list_rejects_non_participant(client, user, other_user):
    s = Session.objects.create(owner=other_user, title="notmine")
    resp = client.get(f"/api/sessions/{s.slug}/messages")
    assert resp.status_code == 404


def test_add_participant_by_email(client, user, other_user):
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    resp = client.post(
        f"/api/sessions/{s.slug}/participants",
        {"email": "bob@dimagi.com"},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.json()["error"] is None
    assert SessionParticipant.objects.filter(session=s, user=other_user).exists()


def test_add_participant_rejects_non_dimagi_email(client, user):
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    resp = client.post(
        f"/api/sessions/{s.slug}/participants",
        {"email": "anyone@example.com"},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_add_participant_rejects_unknown_email(client, user):
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    resp = client.post(
        f"/api/sessions/{s.slug}/participants",
        {"email": "ghost@dimagi.com"},
        format="json",
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_add_participant_rejects_duplicate(client, user, other_user):
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    SessionParticipant.objects.create(session=s, user=other_user, role="editor")
    resp = client.post(
        f"/api/sessions/{s.slug}/participants",
        {"email": "bob@dimagi.com"},
        format="json",
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


def test_add_participant_rejects_non_owner(client, user, other_user, django_user_model):
    s = Session.objects.create(owner=other_user, title="x")
    SessionParticipant.objects.create(session=s, user=other_user, role="owner")
    SessionParticipant.objects.create(session=s, user=user, role="editor")
    # `client` is authenticated as `user`, who is only an editor here.
    resp = client.post(
        f"/api/sessions/{s.slug}/participants",
        {"email": "alice@dimagi.com"},
        format="json",
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
```

- [ ] **Step 8.2: Run the failing test — expect import errors**

Run: `pytest apps/sessions/tests/test_views.py -v`
Expected: FAIL — `messages_list` and `participant_collection` don't exist in `views.py` yet.

- [ ] **Step 8.3: Update `apps/sessions/serializers.py`**

Replace the file with:

```python
"""DRF serializers for Session, Message, Draft, and Participant."""
from __future__ import annotations

from rest_framework import serializers

from .models import Draft, Message, Session, SessionParticipant


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id",
            "turn_index",
            "role",
            "content",
            "plaintext",
            "status",
            "error_detail",
            "started_at",
            "completed_at",
            "created_at",
        ]
        read_only_fields = fields


class SessionSerializer(serializers.ModelSerializer):
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = [
            "slug",
            "title",
            "status",
            "backend_kind",
            "source",
            "cli_session_id",
            "created_at",
            "updated_at",
            "message_count",
        ]
        read_only_fields = [
            "slug", "cli_session_id", "created_at", "updated_at", "message_count",
        ]

    def get_message_count(self, obj: Session) -> int:
        return obj.messages.count()


class SessionDetailSerializer(SessionSerializer):
    """Same as SessionSerializer but includes the full message list."""
    messages = MessageSerializer(many=True, read_only=True)

    class Meta(SessionSerializer.Meta):
        fields = SessionSerializer.Meta.fields + ["messages"]


class DraftSerializer(serializers.ModelSerializer):
    last_edit_at = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Draft
        fields = [
            "id",
            "slot",
            "status",
            "body",
            "version",
            "last_editor",
            "last_edit_at",
        ]
        read_only_fields = fields


class ParticipantSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    display_name = serializers.CharField(
        source="user.display_name", read_only=True
    )

    class Meta:
        model = SessionParticipant
        fields = [
            "user_id",
            "email",
            "display_name",
            "role",
            "joined_at",
            "last_seen_at",
        ]
        read_only_fields = fields
```

- [ ] **Step 8.4: Rewrite `apps/sessions/views.py`**

Replace the file with:

```python
"""REST endpoints for Session CRUD, message read-only listing, and
participant management.

Send is over WebSocket (see apps.sessions.consumers) in Phase 3; the
Phase 2 `send_message` view is deleted.
"""
from __future__ import annotations

from django.db import IntegrityError
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.auth.models import User
from apps.common.envelope import error_response, success_response

from .models import Session, SessionParticipant
from .serializers import (
    MessageSerializer,
    ParticipantSerializer,
    SessionDetailSerializer,
    SessionSerializer,
)


@api_view(["POST", "GET"])
@permission_classes([IsAuthenticated])
def session_collection(request: Request) -> Response:
    if request.method == "POST":
        return _create_session(request)
    return _list_sessions(request)


def _create_session(request: Request) -> Response:
    title = (request.data or {}).get("title", "")
    session = Session.objects.create(owner=request.user, title=title)
    SessionParticipant.objects.create(
        session=session, user=request.user, role="owner"
    )
    return Response(
        success_response(SessionSerializer(session).data),
        status=status.HTTP_201_CREATED,
    )


def _list_sessions(request: Request) -> Response:
    qs = Session.objects.filter(owner=request.user)
    status_filter = request.query_params.get("status")
    if status_filter:
        qs = qs.filter(status=status_filter)
    try:
        limit = int(request.query_params.get("limit", "20"))
    except ValueError:
        limit = 20
    limit = max(1, min(limit, 100))
    qs = qs.order_by("-updated_at")[:limit]
    return Response(success_response(SessionSerializer(qs, many=True).data))


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def session_detail(request: Request, slug: str) -> Response:
    session = _load_session_for_participant(slug, request.user)
    if session is None:
        return _not_found()

    if request.method == "GET":
        return Response(success_response(SessionDetailSerializer(session).data))

    # PATCH — only the owner may edit the session row.
    if session.owner_id != request.user.id:
        return Response(
            error_response(message="only the owner can edit the session", code="forbidden"),
            status=status.HTTP_403_FORBIDDEN,
        )
    allowed = {"title", "status"}
    updates = {k: v for k, v in (request.data or {}).items() if k in allowed}
    if "status" in updates and updates["status"] not in {"active", "archived"}:
        return Response(
            error_response(message="invalid status", code="validation_error"),
            status=400,
        )
    for k, v in updates.items():
        setattr(session, k, v)
    if updates:
        session.save(update_fields=list(updates.keys()) + ["updated_at"])
    return Response(success_response(SessionSerializer(session).data))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def messages_list(request: Request, slug: str) -> Response:
    """Read-only ordered list of messages in a session.

    This is the observation endpoint — the WebSocket consumer is the
    only writer in Phase 3. Tests, curl, and the initial-hydration
    fallback path in the frontend all use this.
    """
    session = _load_session_for_participant(slug, request.user)
    if session is None:
        return _not_found()
    rows = session.messages.all().order_by("turn_index")
    return Response(success_response(MessageSerializer(rows, many=True).data))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def participant_collection(request: Request, slug: str) -> Response:
    """Add a participant by @dimagi.com email. Owner only."""
    session = _load_session_for_participant(slug, request.user)
    if session is None:
        return _not_found()

    if session.owner_id != request.user.id:
        return Response(
            error_response(
                message="only the session owner can add participants",
                code="forbidden",
            ),
            status=status.HTTP_403_FORBIDDEN,
        )

    email = (request.data or {}).get("email", "").strip().lower()
    if not email.endswith("@dimagi.com"):
        return Response(
            error_response(
                message="only @dimagi.com emails may be added",
                code="validation_error",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        return Response(
            error_response(
                message="no user with that email has logged in yet",
                code="not_found",
            ),
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        participant = SessionParticipant.objects.create(
            session=session, user=user, role="editor"
        )
    except IntegrityError:
        return Response(
            error_response(
                message="user is already a participant",
                code="conflict",
            ),
            status=status.HTTP_409_CONFLICT,
        )

    return Response(
        success_response(ParticipantSerializer(participant).data),
        status=status.HTTP_201_CREATED,
    )


# ────────────────────────────── helpers ──────────────────────────────

def _load_session_for_participant(slug: str, user) -> Session | None:
    """Return the session if `user` is a participant, else None.

    Replaces the Phase 2 `owner=request.user` check so editor/viewer
    participants can read the session too.
    """
    try:
        session = Session.objects.get(slug=slug)
    except Session.DoesNotExist:
        return None
    is_participant = SessionParticipant.objects.filter(
        session=session, user=user
    ).exists()
    if not is_participant:
        return None
    return session


def _not_found() -> Response:
    return Response(
        error_response(message="session not found", code="not_found"),
        status=status.HTTP_404_NOT_FOUND,
    )
```

- [ ] **Step 8.5: Run view tests — expect pass**

Run: `pytest apps/sessions/tests/test_views.py -v`
Expected: PASS, all 14 tests.

- [ ] **Step 8.6: Run the full suite to confirm nothing collaterally broken**

Run: `pytest -x`
Expected: all tests pass. Tasks 1–8 are now a complete green state.

- [ ] **Step 8.7: Commit**

```bash
git add apps/sessions/views.py apps/sessions/serializers.py apps/sessions/tests/test_views.py
git commit -m "feat(phase-3): REST surface — messages GET, participant POST, drop send_message"
```

---

## Task 9: SessionConsumer — connect/disconnect/dispatch skeleton

**Files:**
- Create: `apps/sessions/consumers.py`
- Modify: `apps/sessions/routing.py`
- Create: `apps/sessions/tests/test_consumers.py`

- [ ] **Step 9.1: Write the failing test**

Create `apps/sessions/tests/test_consumers.py`:

```python
"""WebsocketCommunicator tests for SessionConsumer.

These tests set up:
- The in-memory channel layer (via config.settings.test).
- fakeredis patched into apps.common.redis_client.get_redis so presence
  and stop-event state is deterministic.
- A signed Django session cookie so the ASGI auth middleware resolves
  the user inside the handshake.
"""
from unittest.mock import patch

import fakeredis.aioredis
import pytest
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore

from apps.common.channels_auth import AceSessionAuthMiddleware
from apps.sessions.models import Session, SessionParticipant
from apps.sessions.routing import websocket_urlpatterns

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _getter():
        return client

    monkeypatch.setattr("apps.common.redis_client.get_redis", _getter)
    yield client
    await client.flushall()
    await client.aclose()


def _build_session_cookie(user):
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    store["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    store["_auth_user_hash"] = user.get_session_auth_hash()
    store.save()
    return store.session_key


def _app():
    return AceSessionAuthMiddleware(URLRouter(websocket_urlpatterns))


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        email="alice@dimagi.com", display_name="Alice"
    )


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(
        email="bob@dimagi.com", display_name="Bob"
    )


@pytest.fixture
def session(alice, bob):
    s = Session.objects.create(owner=alice, title="x")
    SessionParticipant.objects.create(session=s, user=alice, role="owner")
    SessionParticipant.objects.create(session=s, user=bob, role="editor")
    return s


async def _connect(user, slug):
    from django.conf import settings
    cookie_key = _build_session_cookie(user)
    communicator = WebsocketCommunicator(
        _app(),
        f"/ws/sessions/{slug}/",
        headers=[(
            b"cookie",
            f"{settings.SESSION_COOKIE_NAME}={cookie_key}".encode(),
        )],
    )
    connected, _ = await communicator.connect()
    return communicator, connected


async def test_connect_rejects_anonymous(fake_redis, session):
    communicator = WebsocketCommunicator(
        _app(), f"/ws/sessions/{session.slug}/"
    )
    connected, code = await communicator.connect()
    # Consumer accepts then closes with 4001, which WebsocketCommunicator
    # surfaces as (False, 4001).
    assert connected is False
    assert code == 4001


async def test_connect_rejects_non_participant(fake_redis, session, django_user_model):
    stranger = django_user_model.objects.create_user(
        email="stranger@dimagi.com", display_name="Stranger"
    )
    communicator, connected = await _connect(stranger, session.slug)
    assert connected is False


async def test_connect_sends_session_state(fake_redis, session, alice):
    communicator, connected = await _connect(alice, session.slug)
    assert connected is True
    frame = await communicator.receive_json_from()
    assert frame["event"] == "session.state"
    data = frame["data"]
    assert "messages" in data
    assert "active_draft" in data
    assert "participants" in data
    assert "presence_user_ids" in data
    assert alice.id in data["presence_user_ids"]
    assert data["current_user_id"] == alice.id
    await communicator.disconnect()


async def test_alice_draft_update_reaches_bob(fake_redis, session, alice, bob):
    ac, ac_ok = await _connect(alice, session.slug)
    bc, bc_ok = await _connect(bob, session.slug)
    assert ac_ok and bc_ok
    # Drain session.state frames.
    await ac.receive_json_from()
    await bc.receive_json_from()
    # Drain any presence.joined frames Alice sees from Bob's join.
    while True:
        try:
            frame = await ac.receive_json_from(timeout=0.2)
            if frame["event"] != "presence.joined":
                break
        except Exception:
            break

    await ac.send_json_to({
        "action": "draft.update",
        "data": {"version": 0, "body": "Hello Bob"},
    })

    # Both sockets should receive draft.updated.
    ac_frame = await ac.receive_json_from(timeout=1.0)
    bc_frame = None
    for _ in range(4):
        candidate = await bc.receive_json_from(timeout=1.0)
        if candidate["event"] == "draft.updated":
            bc_frame = candidate
            break
    assert ac_frame["event"] == "draft.updated"
    assert bc_frame is not None
    assert bc_frame["data"]["body"] == "Hello Bob"
    assert bc_frame["data"]["version"] == 1

    await ac.disconnect()
    await bc.disconnect()
```

- [ ] **Step 9.2: Run test — expect fail**

Run: `pytest apps/sessions/tests/test_consumers.py -v`
Expected: FAIL — `apps.sessions.routing.websocket_urlpatterns` is still empty and `apps.sessions.consumers` doesn't exist.

- [ ] **Step 9.3: Write the consumer skeleton**

Create `apps/sessions/consumers.py`:

```python
"""SessionConsumer — the single WebSocket endpoint for Phase 3.

Protocol:
  Client → {"action": "<namespace.verb>", "data": {...}}
  Server → {"event": "<namespace.verb>", "data": {...}}

All business logic lives in sibling modules:
  drafts.py       — draft state machine (sync ORM, wrapped in sync_to_async)
  presence.py     — Redis HASH presence + debounced last_seen writer
  turn_driver.py  — assistant streaming loop (async, yields StreamEvents)

This module is the dispatch layer. It translates client actions into
helper calls, broadcasts results to the session's Channels group, and
handles per-connection lifecycle (presence on connect/disconnect, full
state replay on connect, stop-event cleanup).

Channels group naming:  session.{slug}    — all events for a session
Stop-signal Redis key:  turn.stop:{message_id}
"""
from __future__ import annotations

import asyncio
import logging

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db.models import Prefetch

from apps.common.chat_backend import StreamEvent, StreamEventType
from apps.common.redis_client import get_redis

from . import drafts, presence, turn_driver
from .models import Draft, Message, Session, SessionParticipant
from .serializers import (
    DraftSerializer,
    MessageSerializer,
    ParticipantSerializer,
)

logger = logging.getLogger(__name__)

EDITOR_ROLES = {"owner", "editor"}


def _group_name(slug: str) -> str:
    return f"session.{slug}"


class SessionConsumer(AsyncJsonWebsocketConsumer):
    # ─────────────────── lifecycle ───────────────────
    async def connect(self):
        self.slug = self.scope["url_route"]["kwargs"]["slug"]
        user = self.scope.get("user")

        if user is None or not user.is_authenticated:
            await self.accept()
            await self.close(code=4001)
            return

        self.user = user
        self.participant_role = await sync_to_async(_participant_role)(
            self.slug, user.id
        )
        if self.participant_role is None:
            await self.accept()
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(_group_name(self.slug), self.channel_name)
        await self.accept()

        was_new = await presence.touch(self.slug, user.id)
        session_pk = await sync_to_async(_session_pk_for)(self.slug)
        if session_pk is not None:
            await presence.maybe_record_last_seen(
                self.slug, user.id, session_pk=session_pk
            )

        snapshot = await self._build_session_state()
        await self.send_json({"event": "session.state", "data": snapshot})

        if was_new:
            await self.channel_layer.group_send(
                _group_name(self.slug),
                {
                    "type": "presence.joined",
                    "user_id": user.id,
                    "email": user.email,
                    "display_name": user.display_name,
                },
            )

    async def disconnect(self, code):
        slug = getattr(self, "slug", None)
        user = getattr(self, "user", None)
        if slug is None or user is None:
            return
        await presence.leave(slug, user.id)
        await self.channel_layer.group_discard(_group_name(slug), self.channel_name)
        await self.channel_layer.group_send(
            _group_name(slug),
            {"type": "presence.left", "user_id": user.id},
        )

    # ─────────────────── dispatch ───────────────────
    async def receive_json(self, content, **kwargs):
        action = content.get("action")
        data = content.get("data") or {}
        handler = _HANDLERS.get(action)
        if handler is None:
            await self._error("bad_request", f"unknown action {action!r}")
            return
        try:
            await handler(self, data)
        except Exception:
            logger.exception("SessionConsumer handler %s failed", action)
            await self._error("internal", "handler failed")

    # ─────────────────── group event handlers ───────────────────
    async def draft_updated(self, event):
        await self.send_json({"event": "draft.updated", "data": event["data"]})

    async def draft_lock_changed(self, event):
        await self.send_json({"event": "draft.lock_changed", "data": event["data"]})

    async def draft_committed(self, event):
        await self.send_json({"event": "draft.committed", "data": event["data"]})

    async def draft_discarded(self, event):
        await self.send_json({"event": "draft.discarded", "data": event["data"]})

    async def chat_stream_start(self, event):
        await self.send_json({"event": "chat.stream_start", "data": event["data"]})

    async def chat_delta(self, event):
        await self.send_json({"event": "chat.delta", "data": event["data"]})

    async def chat_tool_use(self, event):
        await self.send_json({"event": "chat.tool_use", "data": event["data"]})

    async def chat_tool_result(self, event):
        await self.send_json({"event": "chat.tool_result", "data": event["data"]})

    async def chat_stream_complete(self, event):
        await self.send_json({"event": "chat.stream_complete", "data": event["data"]})

    async def chat_stream_error(self, event):
        await self.send_json({"event": "chat.stream_error", "data": event["data"]})

    async def chat_stream_cancelled(self, event):
        await self.send_json({"event": "chat.stream_cancelled", "data": event["data"]})

    async def presence_joined(self, event):
        await self.send_json({
            "event": "presence.joined",
            "data": {
                "user_id": event["user_id"],
                "email": event["email"],
                "display_name": event["display_name"],
            },
        })

    async def presence_left(self, event):
        await self.send_json({
            "event": "presence.left",
            "data": {"user_id": event["user_id"]},
        })

    # ─────────────────── helpers ───────────────────
    async def _error(self, code: str, message: str, detail: dict | None = None):
        payload = {"code": code, "message": message}
        if detail is not None:
            payload["detail"] = detail
        await self.send_json({"event": "session.error", "data": payload})

    async def _build_session_state(self) -> dict:
        state = await sync_to_async(_sync_build_state)(self.slug, self.user)
        state["presence_user_ids"] = await presence.snapshot(self.slug)
        state["current_user_id"] = self.user.id
        return state

    def _is_editor(self) -> bool:
        return self.participant_role in EDITOR_ROLES


# ────────────────────── handlers ──────────────────────
# Each handler takes (consumer, data) and is async.

async def _handle_presence_heartbeat(consumer: SessionConsumer, data: dict):
    was_new = await presence.touch(consumer.slug, consumer.user.id)
    session_pk = await sync_to_async(_session_pk_for)(consumer.slug)
    if session_pk is not None:
        await presence.maybe_record_last_seen(
            consumer.slug, consumer.user.id, session_pk=session_pk
        )
    if was_new:
        await consumer.channel_layer.group_send(
            _group_name(consumer.slug),
            {
                "type": "presence.joined",
                "user_id": consumer.user.id,
                "email": consumer.user.email,
                "display_name": consumer.user.display_name,
            },
        )


async def _handle_draft_update(consumer: SessionConsumer, data: dict):
    if not consumer._is_editor():
        await consumer._error("forbidden", "viewers cannot edit drafts")
        return
    try:
        version = int(data["version"])
        body = str(data.get("body", ""))
    except (KeyError, TypeError, ValueError):
        await consumer._error("bad_request", "draft.update requires version and body")
        return

    draft_id = await sync_to_async(_active_draft_id)(consumer.slug, consumer.user)
    if draft_id is None:
        await consumer._error("not_found", "no active draft")
        return

    try:
        draft = await sync_to_async(drafts.update_body)(
            draft_id=draft_id,
            user=consumer.user,
            expected_version=version,
            new_body=body,
        )
    except drafts.DraftVersionMismatch as exc:
        await consumer._error(
            "draft_version_mismatch",
            "stale draft version",
            detail={
                "current_version": exc.current_version,
                "current_body": exc.current_body,
            },
        )
        return

    await consumer.channel_layer.group_send(
        _group_name(consumer.slug),
        {"type": "draft.updated", "data": _draft_payload(draft)},
    )


async def _handle_draft_take_over(consumer: SessionConsumer, data: dict):
    if not consumer._is_editor():
        await consumer._error("forbidden", "viewers cannot take over drafts")
        return
    draft_id = await sync_to_async(_active_draft_id)(consumer.slug, consumer.user)
    if draft_id is None:
        await consumer._error("not_found", "no active draft")
        return

    current = await sync_to_async(_current_holder_id)(draft_id)
    holder_present = await presence.is_present(consumer.slug, current)

    try:
        draft = await sync_to_async(drafts.claim_lock)(
            draft_id=draft_id,
            user=consumer.user,
            holder_is_present=holder_present,
        )
    except drafts.DraftLockHeld as exc:
        await consumer._error(
            "draft_lock_held",
            "lock held by another editor",
            detail={
                "holder_user_id": exc.holder_user_id,
                "expires_at": exc.expires_at,
            },
        )
        return

    await consumer.channel_layer.group_send(
        _group_name(consumer.slug),
        {
            "type": "draft.lock_changed",
            "data": {
                "draft_id": draft.id,
                "holder_user_id": draft.last_editor_id,
                "expires_at": None,
            },
        },
    )


async def _handle_draft_discard(consumer: SessionConsumer, data: dict):
    if not consumer._is_editor():
        await consumer._error("forbidden", "viewers cannot discard drafts")
        return
    draft_id = await sync_to_async(_active_draft_id)(consumer.slug, consumer.user)
    if draft_id is None:
        return
    draft = await sync_to_async(drafts.discard)(
        draft_id=draft_id, user=consumer.user
    )
    await consumer.channel_layer.group_send(
        _group_name(consumer.slug),
        {"type": "draft.discarded", "data": {"draft_id": draft.id}},
    )
    await consumer.channel_layer.group_send(
        _group_name(consumer.slug),
        {"type": "draft.updated", "data": _draft_payload(draft)},
    )


async def _handle_chat_send(consumer: SessionConsumer, data: dict):
    if not consumer._is_editor():
        await consumer._error("forbidden", "viewers cannot send messages")
        return
    session = await sync_to_async(_load_session)(consumer.slug)
    if session is None:
        await consumer._error("not_found", "session not found")
        return

    result = await sync_to_async(drafts.commit_active_draft)(
        session=session, user=consumer.user
    )
    if result is None:
        return  # empty draft — silently ignore

    # Broadcast: committed draft + new empty draft + chat.stream_start
    await consumer.channel_layer.group_send(
        _group_name(consumer.slug),
        {
            "type": "draft.committed",
            "data": {
                "draft_id": result.old_draft_id,
                "message_id": result.assistant_message_id,
                "user_message_id": result.user_message_id,
            },
        },
    )
    new_draft = await sync_to_async(_get_draft)(result.new_draft_id)
    await consumer.channel_layer.group_send(
        _group_name(consumer.slug),
        {"type": "draft.updated", "data": _draft_payload(new_draft)},
    )
    await consumer.channel_layer.group_send(
        _group_name(consumer.slug),
        {
            "type": "chat.stream_start",
            "data": {
                "message_id": result.assistant_message_id,
                "turn_index": await sync_to_async(_turn_index_for)(
                    result.assistant_message_id
                ),
            },
        },
    )

    # Spawn the turn driver as a background task owned by this consumer.
    asyncio.create_task(
        _run_turn_driver(consumer, result.assistant_message_id)
    )


async def _handle_chat_stop(consumer: SessionConsumer, data: dict):
    if not consumer._is_editor():
        await consumer._error("forbidden", "viewers cannot stop a stream")
        return
    message_id = data.get("message_id")
    if not isinstance(message_id, int):
        await consumer._error("bad_request", "chat.stop requires message_id")
        return
    r = await get_redis()
    await r.set(f"turn.stop:{message_id}", "1", ex=60)


async def _run_turn_driver(consumer: SessionConsumer, assistant_message_id: int):
    """Run the turn driver and broadcast its events to the session group.

    Polls the Redis stop key each loop iteration via a local
    asyncio.Event mirror, so cross-task cancellation works when a
    different consumer's chat.stop fires.
    """
    stop_event = asyncio.Event()

    async def watch_stop():
        r = await get_redis()
        while not stop_event.is_set():
            value = await r.get(f"turn.stop:{assistant_message_id}")
            if value is not None:
                stop_event.set()
                return
            await asyncio.sleep(0.1)

    watcher = asyncio.create_task(watch_stop())
    try:
        partial = 0
        async for event in turn_driver.drive_assistant_turn(
            assistant_message_id=assistant_message_id, stop_event=stop_event
        ):
            await _broadcast_stream_event(consumer, assistant_message_id, event)
            if event.type is StreamEventType.DELTA and event.text:
                partial += len(event.text)
            if event.type is StreamEventType.DONE:
                await consumer.channel_layer.group_send(
                    _group_name(consumer.slug),
                    {
                        "type": "chat.stream_complete",
                        "data": {
                            "message_id": assistant_message_id,
                            "plaintext": await sync_to_async(_load_plaintext)(
                                assistant_message_id
                            ),
                        },
                    },
                )
                return
            if event.type is StreamEventType.ERROR:
                await consumer.channel_layer.group_send(
                    _group_name(consumer.slug),
                    {
                        "type": "chat.stream_error",
                        "data": {
                            "message_id": assistant_message_id,
                            "detail": event.error or "unknown",
                        },
                    },
                )
                return
        if stop_event.is_set():
            await consumer.channel_layer.group_send(
                _group_name(consumer.slug),
                {
                    "type": "chat.stream_cancelled",
                    "data": {
                        "message_id": assistant_message_id,
                        "partial_len": partial,
                    },
                },
            )
    finally:
        stop_event.set()
        watcher.cancel()
        r = await get_redis()
        await r.delete(f"turn.stop:{assistant_message_id}")


async def _broadcast_stream_event(
    consumer: SessionConsumer, message_id: int, event: StreamEvent
):
    if event.type is StreamEventType.DELTA:
        await consumer.channel_layer.group_send(
            _group_name(consumer.slug),
            {
                "type": "chat.delta",
                "data": {"message_id": message_id, "text": event.text},
            },
        )
    elif event.type is StreamEventType.TOOL_USE:
        tool_id = await sync_to_async(_most_recent_tool_row_id)(
            consumer.slug, "tool_use"
        )
        await consumer.channel_layer.group_send(
            _group_name(consumer.slug),
            {
                "type": "chat.tool_use",
                "data": {
                    "parent_message_id": message_id,
                    "tool_message_id": tool_id,
                    "block": event.tool_block,
                },
            },
        )
    elif event.type is StreamEventType.TOOL_RESULT:
        tool_id = await sync_to_async(_most_recent_tool_row_id)(
            consumer.slug, "tool_result"
        )
        await consumer.channel_layer.group_send(
            _group_name(consumer.slug),
            {
                "type": "chat.tool_result",
                "data": {
                    "parent_message_id": message_id,
                    "tool_message_id": tool_id,
                    "block": event.tool_block,
                },
            },
        )


# ────────────────────── sync DB helpers ──────────────────────

def _participant_role(slug: str, user_id: int) -> str | None:
    row = (
        SessionParticipant.objects.select_related("session")
        .filter(session__slug=slug, user_id=user_id)
        .only("role")
        .first()
    )
    return row.role if row else None


def _session_pk_for(slug: str) -> int | None:
    row = Session.objects.filter(slug=slug).values_list("pk", flat=True).first()
    return row


def _load_session(slug: str) -> Session | None:
    try:
        return Session.objects.get(slug=slug)
    except Session.DoesNotExist:
        return None


def _sync_build_state(slug: str, user) -> dict:
    session = Session.objects.prefetch_related(
        Prefetch("messages"),
        Prefetch("participants__user"),
    ).get(slug=slug)
    messages = list(session.messages.all().order_by("turn_index"))
    participants = list(session.participants.all())
    # Eagerly create the active draft on connect so the client never has
    # to handle a null active_draft and the first keystroke does not race
    # with draft creation.
    active_draft = drafts.get_or_create_active_draft(session, user)
    return {
        "messages": MessageSerializer(messages, many=True).data,
        "active_draft": DraftSerializer(active_draft).data,
        "participants": ParticipantSerializer(participants, many=True).data,
    }


def _active_draft_id(slug: str, user) -> int | None:
    try:
        session = Session.objects.get(slug=slug)
    except Session.DoesNotExist:
        return None
    draft = drafts.get_or_create_active_draft(session, user)
    return draft.id


def _current_holder_id(draft_id: int) -> int:
    return Draft.objects.filter(pk=draft_id).values_list("last_editor_id", flat=True).first()


def _get_draft(draft_id: int) -> Draft:
    return Draft.objects.get(pk=draft_id)


def _load_plaintext(message_id: int) -> str:
    return Message.objects.filter(pk=message_id).values_list("plaintext", flat=True).first() or ""


def _turn_index_for(message_id: int) -> int:
    return Message.objects.filter(pk=message_id).values_list("turn_index", flat=True).first() or 0


def _most_recent_tool_row_id(slug: str, role: str) -> int:
    return (
        Message.objects.filter(session__slug=slug, role=role)
        .order_by("-turn_index")
        .values_list("pk", flat=True)
        .first()
    ) or 0


def _draft_payload(draft: Draft) -> dict:
    return DraftSerializer(draft).data


_HANDLERS = {
    "chat.send": _handle_chat_send,
    "chat.stop": _handle_chat_stop,
    "draft.update": _handle_draft_update,
    "draft.take_over": _handle_draft_take_over,
    "draft.discard": _handle_draft_discard,
    "presence.heartbeat": _handle_presence_heartbeat,
}
```

- [ ] **Step 9.4: Update `apps/sessions/routing.py`**

Replace the file with:

```python
"""WebSocket routing for sessions."""
from django.urls import path

from .consumers import SessionConsumer

websocket_urlpatterns = [
    path("ws/sessions/<slug:slug>/", SessionConsumer.as_asgi()),
]
```

- [ ] **Step 9.5: Run consumer tests — expect pass**

Run: `pytest apps/sessions/tests/test_consumers.py -v`
Expected: PASS, all 4 tests.

- [ ] **Step 9.6: Run the full suite**

Run: `pytest -x`
Expected: all tests green.

- [ ] **Step 9.7: Commit**

```bash
git add apps/sessions/consumers.py apps/sessions/routing.py apps/sessions/tests/test_consumers.py
git commit -m "feat(phase-3): SessionConsumer with connect/dispatch/draft/chat/presence handlers"
```

---

## Task 10: End-to-end consumer tests — chat send + stream broadcast

**Files:**
- Modify: `apps/sessions/tests/test_consumers.py` (add new tests)

- [ ] **Step 10.1: Add the failing tests to `test_consumers.py`**

Append these tests to `apps/sessions/tests/test_consumers.py`:

```python
from unittest.mock import patch

from apps.common.chat_backend import StreamEvent


class _FakeBackend:
    def __init__(self, events):
        self._events = events

    async def stream_completion(self, *, session, new_user_message, **kwargs):
        for e in self._events:
            yield e


async def _drain_until(communicator, event_name, timeout=2.0):
    """Receive frames until the named event arrives or timeout."""
    import asyncio

    async def _loop():
        while True:
            frame = await communicator.receive_json_from()
            if frame["event"] == event_name:
                return frame

    return await asyncio.wait_for(_loop(), timeout=timeout)


async def test_chat_send_broadcasts_stream_to_both_users(
    fake_redis, session, alice, bob
):
    events = [
        StreamEvent.delta(text="Hel"),
        StreamEvent.delta(text="lo"),
        StreamEvent.done(),
    ]

    ac, ac_ok = await _connect(alice, session.slug)
    bc, bc_ok = await _connect(bob, session.slug)
    assert ac_ok and bc_ok
    await ac.receive_json_from()  # drain session.state
    await bc.receive_json_from()  # drain session.state

    # Alice writes the draft, then sends.
    await ac.send_json_to({
        "action": "draft.update",
        "data": {"version": 0, "body": "hi"},
    })
    await _drain_until(ac, "draft.updated")
    await _drain_until(bc, "draft.updated")

    with patch(
        "apps.sessions.turn_driver._get_backend",
        return_value=_FakeBackend(events),
    ):
        await ac.send_json_to({"action": "chat.send", "data": {}})

        # Both users should see chat.stream_start → chat.delta × 2 → chat.stream_complete.
        for comm in (ac, bc):
            await _drain_until(comm, "chat.stream_start")
            delta1 = await _drain_until(comm, "chat.delta")
            assert delta1["data"]["text"] == "Hel"
            delta2 = await _drain_until(comm, "chat.delta")
            assert delta2["data"]["text"] == "lo"
            await _drain_until(comm, "chat.stream_complete")

    await ac.disconnect()
    await bc.disconnect()


async def test_chat_stop_from_bob_cancels_alice_stream(
    fake_redis, session, alice, bob
):
    import asyncio

    class SlowBackend:
        async def stream_completion(self, **kwargs):
            yield StreamEvent.delta(text="partial ")
            await asyncio.sleep(60)
            yield StreamEvent.done()

    ac, ac_ok = await _connect(alice, session.slug)
    bc, bc_ok = await _connect(bob, session.slug)
    assert ac_ok and bc_ok
    await ac.receive_json_from()
    await bc.receive_json_from()

    await ac.send_json_to({
        "action": "draft.update",
        "data": {"version": 0, "body": "stop me"},
    })
    await _drain_until(ac, "draft.updated")
    await _drain_until(bc, "draft.updated")

    with patch(
        "apps.sessions.turn_driver._get_backend",
        return_value=SlowBackend(),
    ):
        await ac.send_json_to({"action": "chat.send", "data": {}})

        start_frame = await _drain_until(bc, "chat.stream_start")
        message_id = start_frame["data"]["message_id"]

        # Wait for Bob to see at least one delta before issuing stop.
        await _drain_until(bc, "chat.delta")

        await bc.send_json_to({
            "action": "chat.stop",
            "data": {"message_id": message_id},
        })

        # Both users should eventually see stream_cancelled.
        await _drain_until(ac, "chat.stream_cancelled")
        await _drain_until(bc, "chat.stream_cancelled")

    await ac.disconnect()
    await bc.disconnect()


async def test_draft_take_over_fails_on_live_lock(fake_redis, session, alice, bob):
    ac, _ = await _connect(alice, session.slug)
    bc, _ = await _connect(bob, session.slug)
    await ac.receive_json_from()
    await bc.receive_json_from()

    await ac.send_json_to({
        "action": "draft.update",
        "data": {"version": 0, "body": "mine"},
    })
    await _drain_until(ac, "draft.updated")

    await bc.send_json_to({"action": "draft.take_over", "data": {}})
    frame = await bc.receive_json_from(timeout=1.0)
    assert frame["event"] == "session.error"
    assert frame["data"]["code"] == "draft_lock_held"

    await ac.disconnect()
    await bc.disconnect()
```

- [ ] **Step 10.2: Run the tests — expect pass**

Run: `pytest apps/sessions/tests/test_consumers.py -v`
Expected: PASS, all 7 tests (4 from Task 9 + 3 new).

If a test hangs, the likely cause is that an earlier event in the stream was not drained; inspect the order of `_drain_until` calls and the handler chain in `consumers.py`.

- [ ] **Step 10.3: Commit**

```bash
git add apps/sessions/tests/test_consumers.py
git commit -m "test(phase-3): consumer integration tests for chat send, stop, and lock contention"
```

---

## Task 11: Frontend — `useSessionSocket` hook

**Files:**
- Create: `frontend/src/hooks/useSessionSocket.ts`
- Delete: `frontend/src/hooks/useStreamingMessage.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/messages.ts`
- Create: `frontend/src/api/participants.ts`

- [ ] **Step 11.1: Add Phase 3 types**

Replace the top portion of `frontend/src/api/types.ts` (keep the ACE Workbench section at the bottom untouched):

```ts
export type SessionStatus = "active" | "archived" | "imported";
export type BackendKind = "cli" | "api" | "mcp";
export type SessionSource = "web" | "upload";
export type MessageStatus = "pending" | "streaming" | "complete" | "error";
export type MessageRole =
  | "user"
  | "assistant"
  | "system"
  | "tool_use"
  | "tool_result";

export interface Session {
  slug: string;
  title: string;
  status: SessionStatus;
  backend_kind: BackendKind;
  source: SessionSource;
  cli_session_id: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface SessionDetail extends Session {
  messages: Message[];
}

export interface Message {
  id: number;
  turn_index: number;
  role: MessageRole;
  content: Record<string, unknown>;
  plaintext: string;
  status: MessageStatus;
  error_detail: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface Draft {
  id: number;
  slot: "next" | "queued";
  status: "open" | "sent" | "discarded";
  body: string;
  version: number;
  last_editor: number;
  last_edit_at: string;
}

export interface Participant {
  user_id: number;
  email: string;
  display_name: string;
  role: "owner" | "editor" | "viewer";
  joined_at: string;
  last_seen_at: string | null;
}

export interface SessionState {
  messages: Message[];
  active_draft: Draft | null;
  participants: Participant[];
  presence_user_ids: number[];
  current_user_id: number;
}

// WebSocket protocol ------------------------------------------------------

export type WsAction =
  | { action: "chat.send"; data: Record<string, never> }
  | { action: "chat.stop"; data: { message_id: number } }
  | { action: "draft.update"; data: { version: number; body: string } }
  | { action: "draft.take_over"; data: Record<string, never> }
  | { action: "draft.discard"; data: Record<string, never> }
  | { action: "presence.heartbeat"; data: Record<string, never> };

export type WsEvent =
  | { event: "session.state"; data: SessionState }
  | { event: "session.error"; data: { code: string; message: string; detail?: unknown } }
  | { event: "chat.stream_start"; data: { message_id: number; turn_index: number } }
  | { event: "chat.delta"; data: { message_id: number; text: string } }
  | { event: "chat.tool_use"; data: { parent_message_id: number; tool_message_id: number; block: Record<string, unknown> } }
  | { event: "chat.tool_result"; data: { parent_message_id: number; tool_message_id: number; block: Record<string, unknown> } }
  | { event: "chat.stream_complete"; data: { message_id: number; plaintext: string } }
  | { event: "chat.stream_error"; data: { message_id: number; detail: string } }
  | { event: "chat.stream_cancelled"; data: { message_id: number; partial_len: number } }
  | { event: "draft.updated"; data: Draft }
  | { event: "draft.lock_changed"; data: { draft_id: number; holder_user_id: number | null; expires_at: number | null } }
  | { event: "draft.committed"; data: { draft_id: number; message_id: number; user_message_id: number } }
  | { event: "draft.discarded"; data: { draft_id: number } }
  | { event: "presence.joined"; data: { user_id: number; email: string; display_name: string } }
  | { event: "presence.left"; data: { user_id: number } };

export interface ApiEnvelope<T> {
  data: T | null;
  error: { code: string; message: string } | null;
}

export interface CliAuthStatus {
  authenticated: boolean;
}

export interface CliAuthStartResult {
  auth_url: string | null;
  token: string | null;
  status: "complete" | "awaiting_code";
}

export interface CliAuthPollResult {
  active: boolean;
  authenticated: boolean;
  elapsed_seconds?: number;
}
```

(Everything below this — the ACE Workbench types starting with `// --- ACE Opportunity Workbench types ---` — stays exactly as it is.)

- [ ] **Step 11.2: Replace `frontend/src/api/messages.ts`**

```ts
import { apiFetch } from "./client";
import type { Message } from "./types";

export const listMessages = (slug: string) =>
  apiFetch<Message[]>(`/api/sessions/${slug}/messages`);
```

- [ ] **Step 11.3: Create `frontend/src/api/participants.ts`**

```ts
import { apiFetch } from "./client";
import type { Participant } from "./types";

export const addParticipant = (slug: string, email: string) =>
  apiFetch<Participant>(`/api/sessions/${slug}/participants`, {
    method: "POST",
    body: JSON.stringify({ email }),
  });
```

- [ ] **Step 11.4: Delete `useStreamingMessage.ts`**

```bash
rm frontend/src/hooks/useStreamingMessage.ts
```

- [ ] **Step 11.5: Create `useSessionSocket.ts`**

Create `frontend/src/hooks/useSessionSocket.ts`:

```ts
import { useCallback, useEffect, useRef, useState } from "react";

import type {
  Draft,
  Message,
  Participant,
  SessionState,
  WsEvent,
} from "../api/types";

const HEARTBEAT_INTERVAL_MS = 20_000;
const RECONNECT_DELAYS_MS = [1_000, 2_000, 5_000, 10_000];
const DRAFT_UPDATE_DEBOUNCE_MS = 150;

const INITIAL_STATE: SessionState = {
  messages: [],
  active_draft: null,
  participants: [],
  presence_user_ids: [],
  current_user_id: 0,
};

function wsUrlFor(slug: string): string {
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${base}/ws/sessions/${slug}/`;
}

export interface UseSessionSocketResult {
  state: SessionState;
  connected: boolean;
  sendChat: () => void;
  stopChat: (messageId: number) => void;
  updateDraft: (body: string) => void;
  takeOverDraft: () => void;
  discardDraft: () => void;
  lastError: string | null;
}

export function useSessionSocket(slug: string): UseSessionSocketResult {
  const [state, setState] = useState<SessionState>(INITIAL_STATE);
  const [connected, setConnected] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const stateRef = useRef<SessionState>(INITIAL_STATE);
  const reconnectAttemptRef = useRef(0);
  const heartbeatTimerRef = useRef<number | null>(null);
  const draftDebounceRef = useRef<number | null>(null);
  const pendingDraftBodyRef = useRef<string | null>(null);
  const closedByUserRef = useRef(false);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const send = useCallback((frame: { action: string; data: unknown }) => {
    const ws = socketRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(frame));
    }
  }, []);

  const applyEvent = useCallback((frame: WsEvent) => {
    setState((prev) => {
      switch (frame.event) {
        case "session.state":
          return frame.data;
        case "chat.stream_start": {
          // Flip the matching message to streaming if present; otherwise wait
          // for the next GET-messages-fallback or reconnect to rehydrate.
          return {
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === frame.data.message_id
                ? { ...m, status: "streaming" as const }
                : m,
            ),
          };
        }
        case "chat.delta":
          return {
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === frame.data.message_id
                ? { ...m, plaintext: m.plaintext + frame.data.text }
                : m,
            ),
          };
        case "chat.stream_complete":
          return {
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === frame.data.message_id
                ? {
                    ...m,
                    plaintext: frame.data.plaintext,
                    status: "complete" as const,
                  }
                : m,
            ),
          };
        case "chat.stream_error":
          return {
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === frame.data.message_id
                ? {
                    ...m,
                    status: "error" as const,
                    error_detail: frame.data.detail,
                  }
                : m,
            ),
          };
        case "chat.stream_cancelled":
          return {
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === frame.data.message_id
                ? {
                    ...m,
                    status: "error" as const,
                    error_detail: `cancelled (partial: ${frame.data.partial_len} chars)`,
                  }
                : m,
            ),
          };
        case "chat.tool_use":
        case "chat.tool_result":
          // Tool rows are their own Message rows on the server. A full
          // refresh picks them up; for now, don't duplicate bookkeeping.
          return prev;
        case "draft.updated":
          return { ...prev, active_draft: frame.data as Draft };
        case "draft.lock_changed":
          if (prev.active_draft && prev.active_draft.id === frame.data.draft_id) {
            return {
              ...prev,
              active_draft: {
                ...prev.active_draft,
                last_editor: frame.data.holder_user_id ?? prev.active_draft.last_editor,
              },
            };
          }
          return prev;
        case "draft.committed":
          return prev;
        case "draft.discarded":
          if (prev.active_draft && prev.active_draft.id === frame.data.draft_id) {
            return {
              ...prev,
              active_draft: { ...prev.active_draft, body: "" },
            };
          }
          return prev;
        case "presence.joined": {
          const ids = new Set(prev.presence_user_ids);
          ids.add(frame.data.user_id);
          return { ...prev, presence_user_ids: [...ids] };
        }
        case "presence.left":
          return {
            ...prev,
            presence_user_ids: prev.presence_user_ids.filter(
              (id) => id !== frame.data.user_id,
            ),
          };
        case "session.error":
          setLastError(frame.data.message);
          return prev;
        default:
          return prev;
      }
    });
  }, []);

  const connect = useCallback(() => {
    if (closedByUserRef.current) return;
    const ws = new WebSocket(wsUrlFor(slug));
    socketRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      reconnectAttemptRef.current = 0;
      // Start heartbeat timer.
      if (heartbeatTimerRef.current != null) {
        window.clearInterval(heartbeatTimerRef.current);
      }
      heartbeatTimerRef.current = window.setInterval(() => {
        send({ action: "presence.heartbeat", data: {} });
      }, HEARTBEAT_INTERVAL_MS);
    };

    ws.onmessage = (e) => {
      try {
        const frame = JSON.parse(e.data) as WsEvent;
        applyEvent(frame);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = () => {
      setConnected(false);
      if (heartbeatTimerRef.current != null) {
        window.clearInterval(heartbeatTimerRef.current);
        heartbeatTimerRef.current = null;
      }
      if (closedByUserRef.current) return;
      const attempt = reconnectAttemptRef.current;
      const delay = RECONNECT_DELAYS_MS[
        Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)
      ];
      reconnectAttemptRef.current = attempt + 1;
      window.setTimeout(connect, delay);
    };

    ws.onerror = () => {
      // onclose will fire next; nothing to do here.
    };
  }, [applyEvent, send, slug]);

  useEffect(() => {
    closedByUserRef.current = false;
    reconnectAttemptRef.current = 0;
    connect();
    return () => {
      closedByUserRef.current = true;
      if (heartbeatTimerRef.current != null) {
        window.clearInterval(heartbeatTimerRef.current);
      }
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
    };
  }, [connect]);

  const sendChat = useCallback(() => {
    // Flush any pending debounced update first so the committed draft
    // carries the latest local body.
    if (draftDebounceRef.current != null) {
      window.clearTimeout(draftDebounceRef.current);
      draftDebounceRef.current = null;
      if (pendingDraftBodyRef.current != null && stateRef.current.active_draft) {
        send({
          action: "draft.update",
          data: {
            version: stateRef.current.active_draft.version,
            body: pendingDraftBodyRef.current,
          },
        });
        pendingDraftBodyRef.current = null;
      }
    }
    send({ action: "chat.send", data: {} });
  }, [send]);

  const stopChat = useCallback(
    (messageId: number) => {
      send({ action: "chat.stop", data: { message_id: messageId } });
    },
    [send],
  );

  const updateDraft = useCallback(
    (body: string) => {
      // Optimistic local update so the textarea feels snappy.
      setState((prev) =>
        prev.active_draft
          ? { ...prev, active_draft: { ...prev.active_draft, body } }
          : prev,
      );
      pendingDraftBodyRef.current = body;
      if (draftDebounceRef.current != null) {
        window.clearTimeout(draftDebounceRef.current);
      }
      draftDebounceRef.current = window.setTimeout(() => {
        draftDebounceRef.current = null;
        const current = stateRef.current.active_draft;
        const pending = pendingDraftBodyRef.current;
        pendingDraftBodyRef.current = null;
        if (current != null && pending != null) {
          send({
            action: "draft.update",
            data: { version: current.version, body: pending },
          });
        }
      }, DRAFT_UPDATE_DEBOUNCE_MS);
    },
    [send],
  );

  const takeOverDraft = useCallback(() => {
    send({ action: "draft.take_over", data: {} });
  }, [send]);

  const discardDraft = useCallback(() => {
    send({ action: "draft.discard", data: {} });
  }, [send]);

  return {
    state,
    connected,
    sendChat,
    stopChat,
    updateDraft,
    takeOverDraft,
    discardDraft,
    lastError,
  };
}
```

- [ ] **Step 11.6: Run the frontend type-check**

Run: `cd frontend && bun run build` (or `npm run build` / `tsc --noEmit` — whichever the repo uses).
Expected: build succeeds, no type errors. The chat page will be broken at this step because it still imports `useStreamingMessage` — that's fixed in Task 12.

- [ ] **Step 11.7: Commit**

```bash
git add frontend/src/hooks/useSessionSocket.ts frontend/src/hooks/useStreamingMessage.ts frontend/src/api/types.ts frontend/src/api/messages.ts frontend/src/api/participants.ts
git commit -m "feat(phase-3): useSessionSocket hook + WebSocket protocol types"
```

---

## Task 12: Frontend — rewire ChatPage, SendBox, presence UI

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`
- Modify: `frontend/src/components/SendBox.tsx`
- Modify: `frontend/src/components/MessageList.tsx`
- Create: `frontend/src/components/PresenceChips.tsx`
- Create: `frontend/src/components/AddTeammateButton.tsx`

- [ ] **Step 12.1: Create `PresenceChips.tsx`**

```tsx
import type { Participant } from "../api/types";

interface Props {
  participants: Participant[];
  presenceUserIds: number[];
  draftHolderId: number | null;
  draftHolderIdle: boolean;
}

export function PresenceChips({
  participants,
  presenceUserIds,
  draftHolderId,
  draftHolderIdle,
}: Props) {
  const present = participants.filter((p) =>
    presenceUserIds.includes(p.user_id),
  );
  if (present.length === 0) {
    return <div className="text-sm text-zinc-400">nobody else here</div>;
  }
  return (
    <div className="flex gap-2">
      {present.map((p) => {
        const isHolder = p.user_id === draftHolderId && !draftHolderIdle;
        return (
          <div
            key={p.user_id}
            title={p.display_name + (isHolder ? " — editing…" : "")}
            className={`rounded-full px-2 py-1 text-xs ${
              isHolder
                ? "bg-amber-200 text-amber-900"
                : "bg-zinc-200 text-zinc-700"
            }`}
          >
            {initials(p.display_name)}
          </div>
        );
      })}
    </div>
  );
}

function initials(name: string): string {
  return name
    .split(" ")
    .map((w) => w[0])
    .filter(Boolean)
    .join("")
    .slice(0, 2)
    .toUpperCase();
}
```

- [ ] **Step 12.2: Create `AddTeammateButton.tsx`**

```tsx
import { useState } from "react";

import { addParticipant } from "../api/participants";

interface Props {
  slug: string;
  onAdded?: () => void;
}

export function AddTeammateButton({ slug, onAdded }: Props) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await addParticipant(slug, email.trim().toLowerCase());
      setOpen(false);
      setEmail("");
      onAdded?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to add teammate");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        className="rounded border border-zinc-300 px-2 py-1 text-xs text-zinc-600 hover:bg-zinc-100"
        onClick={() => setOpen(true)}
      >
        + teammate
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <input
        type="email"
        placeholder="name@dimagi.com"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        className="rounded border border-zinc-300 px-2 py-1 text-xs"
      />
      <button
        type="button"
        disabled={submitting || !email.includes("@")}
        className="rounded bg-blue-600 px-2 py-1 text-xs text-white disabled:opacity-40"
        onClick={submit}
      >
        add
      </button>
      <button
        type="button"
        className="text-xs text-zinc-500"
        onClick={() => {
          setOpen(false);
          setError(null);
        }}
      >
        cancel
      </button>
      {error ? <span className="text-xs text-rose-600">{error}</span> : null}
    </div>
  );
}
```

- [ ] **Step 12.3: Rewrite `SendBox.tsx`**

Replace `frontend/src/components/SendBox.tsx` with:

```tsx
import { useEffect, useRef } from "react";

import type { Draft } from "../api/types";

interface Props {
  draft: Draft | null;
  currentUserId: number;
  holderIsPresent: boolean;
  isStreaming: boolean;
  streamingMessageId: number | null;
  onUpdate: (body: string) => void;
  onSend: () => void;
  onStop: (messageId: number) => void;
  onTakeOver: () => void;
}

const IDLE_THRESHOLD_MS = 2_000;

export function SendBox({
  draft,
  currentUserId,
  holderIsPresent,
  isStreaming,
  streamingMessageId,
  onUpdate,
  onSend,
  onStop,
  onTakeOver,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const holderId = draft?.last_editor ?? null;
  const isHolder = holderId === currentUserId;
  const lastEditAt = draft ? new Date(draft.last_edit_at).getTime() : 0;
  const holderIsIdle = draft ? Date.now() - lastEditAt > IDLE_THRESHOLD_MS : true;
  // Textarea editable if: you are the holder OR the lock is idle OR the holder is absent.
  const canEdit = isHolder || holderIsIdle || !holderIsPresent;

  useEffect(() => {
    if (canEdit && !isHolder && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [canEdit, isHolder]);

  const body = draft?.body ?? "";
  const canSend = canEdit && body.trim().length > 0 && !isStreaming;

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend) onSend();
    }
  };

  const handleStopClick = () => {
    if (streamingMessageId != null) onStop(streamingMessageId);
  };

  return (
    <div className="border-t border-zinc-200 p-2">
      <textarea
        ref={textareaRef}
        value={body}
        readOnly={!canEdit}
        disabled={!canEdit}
        onChange={(e) => onUpdate(e.target.value)}
        onKeyDown={handleKey}
        placeholder={
          canEdit
            ? "Type a message… (Enter to send, Shift+Enter for newline)"
            : "Another teammate is editing…"
        }
        rows={3}
        className="w-full resize-none rounded border border-zinc-300 p-2 text-sm disabled:bg-zinc-50 disabled:text-zinc-500"
      />
      <div className="mt-1 flex justify-end gap-2">
        {isStreaming ? (
          <button
            type="button"
            onClick={handleStopClick}
            className="rounded bg-rose-600 px-3 py-1 text-sm text-white"
          >
            stop
          </button>
        ) : null}
        {!canEdit && holderIsPresent && !holderIsIdle ? (
          <button
            type="button"
            disabled
            onClick={onTakeOver}
            className="rounded border border-zinc-300 px-3 py-1 text-sm text-zinc-400"
          >
            take over
          </button>
        ) : null}
        <button
          type="button"
          disabled={!canSend}
          onClick={onSend}
          className="rounded bg-blue-600 px-3 py-1 text-sm text-white disabled:opacity-40"
        >
          send
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 12.4: Modify `MessageList.tsx`**

Open `frontend/src/components/MessageList.tsx` and replace its contents with:

```tsx
import type { Message } from "../api/types";

import { MessageItem } from "./MessageItem";

interface Props {
  messages: Message[];
}

export function MessageList({ messages }: Props) {
  return (
    <div className="flex flex-col gap-4 p-4">
      {messages.map((m) => (
        <MessageItem key={m.id} message={m} />
      ))}
    </div>
  );
}
```

(The Phase 2 props — `liveAssistantId` and `liveText` — are gone. A streaming message's current text now lives in `message.plaintext` because the hook writes it there incrementally.)

Then replace `frontend/src/components/MessageItem.tsx` with:

```tsx
import type { Message } from "../api/types";

interface Props {
  message: Message;
}

export function MessageItem({ message }: Props) {
  const text = message.plaintext;
  const isStreaming = message.status === "streaming";

  if (message.role === "tool_use") {
    return (
      <details className="my-2 rounded border border-zinc-200 bg-zinc-50 p-2 text-sm">
        <summary className="cursor-pointer text-zinc-600">
          tool_use: {String(message.content?.name ?? "unknown")}
        </summary>
        <pre className="mt-2 whitespace-pre-wrap text-xs text-zinc-700">
          {JSON.stringify(message.content, null, 2)}
        </pre>
      </details>
    );
  }
  if (message.role === "tool_result") {
    return (
      <details className="my-2 rounded border border-zinc-200 bg-zinc-50 p-2 text-sm">
        <summary className="cursor-pointer text-zinc-600">tool_result</summary>
        <pre className="mt-2 whitespace-pre-wrap text-xs text-zinc-700">
          {message.plaintext}
        </pre>
      </details>
    );
  }

  const bubbleClass =
    message.role === "user"
      ? "ml-auto bg-blue-600 text-white"
      : "mr-auto bg-zinc-100 text-zinc-900";
  return (
    <div
      className={`my-2 max-w-[80%] rounded-2xl px-4 py-2 ${bubbleClass}`}
      aria-live={isStreaming ? "polite" : undefined}
    >
      <div className="whitespace-pre-wrap">{text}</div>
      {isStreaming && (
        <span className="ml-1 inline-block h-3 w-1 animate-pulse bg-current align-middle" />
      )}
    </div>
  );
}
```

- [ ] **Step 12.5: Rewrite `ChatPage.tsx`**

Replace `frontend/src/pages/ChatPage.tsx` with:

```tsx
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { getSession, updateSession } from "../api/sessions";
import { AddTeammateButton } from "../components/AddTeammateButton";
import { CliAuthBanner } from "../components/CliAuthBanner";
import { InlineTitleEdit } from "../components/InlineTitleEdit";
import { MessageList } from "../components/MessageList";
import { PresenceChips } from "../components/PresenceChips";
import { RecentSessionsSidebar } from "../components/RecentSessionsSidebar";
import { SendBox } from "../components/SendBox";
import { useSessionSocket } from "../hooks/useSessionSocket";
import type { Session } from "../api/types";

export function ChatPage() {
  const { slug = "" } = useParams();
  const [meta, setMeta] = useState<Session | null>(null);
  const socket = useSessionSocket(slug);

  useEffect(() => {
    if (!slug) return;
    getSession(slug).then((s) => setMeta(s));
  }, [slug]);

  // The consumer sends current_user_id in session.state, so we can
  // read it straight off the socket state.
  const currentUserId = socket.state.current_user_id;

  const holderId = socket.state.active_draft?.last_editor ?? null;
  const holderIsPresent =
    holderId != null && socket.state.presence_user_ids.includes(holderId);

  const streamingMessage = useMemo(() => {
    return socket.state.messages.find((m) => m.status === "streaming") ?? null;
  }, [socket.state.messages]);

  const handleTitleSave = async (newTitle: string) => {
    if (!meta) return;
    const updated = await updateSession(slug, { title: newTitle });
    setMeta({ ...meta, title: updated.title });
  };

  if (!meta) {
    return <div className="p-4 text-zinc-500">Loading…</div>;
  }

  return (
    <div className="flex h-screen">
      <RecentSessionsSidebar currentSlug={slug} />
      <div className="flex flex-1 flex-col">
        <CliAuthBanner />
        <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-2">
          <InlineTitleEdit value={meta.title} onSave={handleTitleSave} />
          <div className="flex items-center gap-3">
            <PresenceChips
              participants={socket.state.participants}
              presenceUserIds={socket.state.presence_user_ids}
              draftHolderId={holderId}
              draftHolderIdle={isIdle(socket.state.active_draft?.last_edit_at)}
            />
            <AddTeammateButton slug={slug} />
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">
          <MessageList messages={socket.state.messages} />
        </main>
        <SendBox
          draft={socket.state.active_draft}
          currentUserId={currentUserId}
          holderIsPresent={holderIsPresent}
          isStreaming={streamingMessage != null}
          streamingMessageId={streamingMessage?.id ?? null}
          onUpdate={socket.updateDraft}
          onSend={socket.sendChat}
          onStop={socket.stopChat}
          onTakeOver={socket.takeOverDraft}
        />
      </div>
    </div>
  );
}

function isIdle(lastEditAt: string | undefined): boolean {
  if (!lastEditAt) return true;
  return Date.now() - new Date(lastEditAt).getTime() > 2_000;
}
```

- [ ] **Step 12.6: Build the frontend**

Run: `cd frontend && bun run build`
Expected: build succeeds, no type errors.

- [ ] **Step 12.7: Commit**

```bash
git add frontend/src/pages/ChatPage.tsx frontend/src/components/SendBox.tsx frontend/src/components/MessageList.tsx frontend/src/components/MessageItem.tsx frontend/src/components/PresenceChips.tsx frontend/src/components/AddTeammateButton.tsx
git commit -m "feat(phase-3): ChatPage on WebSocket; draft-aware SendBox; presence chips"
```

---

## Task 13: Deploy wiring for REDIS_URL on AWS

**Files:**
- Modify: `deploy/aws/task-definition.json`
- Modify: `docs/deploy.md`

- [ ] **Step 13.1: Add the secrets reference to the task definition**

Open `deploy/aws/task-definition.json`. Find the `secrets` array for the `app` container and add an entry for `REDIS_URL`. The exact shape follows the sibling entries (e.g., `DATABASE_URL`, `DJANGO_SECRET_KEY`); copy one and retarget it at the new Secrets Manager ARN.

Example added entry (replace `<ACCOUNT>` and `<SECRET_NAME>` with real values already documented in `docs/deploy.md`):

```json
{
  "name": "REDIS_URL",
  "valueFrom": "arn:aws:secretsmanager:us-east-1:<ACCOUNT>:secret:<SECRET_NAME>:REDIS_URL::"
}
```

The shared connect-labs ElastiCache endpoint should already exist as a secret value in the connect-labs scope. If it is not already present in the ace-web secret, coordinate with the connect-labs ops contact to add it or use an existing shared secret reference.

- [ ] **Step 13.2: Update `docs/deploy.md`**

Add a new subsection under the existing "Secrets" or "Environment variables" heading:

```markdown
### REDIS_URL (Phase 3)

`REDIS_URL` points at the shared connect-labs AWS ElastiCache Redis
endpoint. It is consumed by:

- `CHANNEL_LAYERS` in `config/settings/base.py` — the channels-redis
  backend for cross-task WebSocket broadcast.
- `apps.common.redis_client.get_redis()` — the shared async client used
  by `apps.sessions.presence` and the turn-stop signal.

The secret is stored in AWS Secrets Manager alongside `DATABASE_URL` and
`DJANGO_SECRET_KEY`. Local dev uses `redis://redis:6379/0` via the
docker-compose `redis` service.

Before scaling ECS desired count past 1, confirm the secret resolves in
the running task with `aws ecs execute-command ... -- env | grep REDIS_URL`
and verify presence replication works by opening a session in two
browser tabs pinned to different tasks.
```

- [ ] **Step 13.3: Commit**

```bash
git add deploy/aws/task-definition.json docs/deploy.md
git commit -m "feat(phase-3): AWS task definition + deploy docs for REDIS_URL"
```

---

## Task 14: Learnings and CLAUDE.md

**Files:**
- Modify: `docs/learnings/channels-single-instance.md`
- Create: `docs/learnings/channels-websocket-auth.md`
- Create: `docs/learnings/redis-presence-hash.md`
- Modify: `CLAUDE.md`

- [ ] **Step 14.1: Update `docs/learnings/channels-single-instance.md`**

Prepend a new top-level "Resolution" section and update the `Status` line:

```markdown
# Learning: InMemoryChannelLayer forces a single ECS Fargate task

**Date**: 2026-04-08
**Context**: Plan 1A `config/settings/base.py`. Blocker for scaling beyond a single instance.
**Status**: Resolved in Phase 3 (see `docs/plans/2026-04-09-3-multi-player.md` Task 2).

## Resolution

Phase 3 swapped `CHANNEL_LAYERS` in `config/settings/base.py` to
`channels_redis.core.RedisChannelLayer` pointing at `REDIS_URL`. The
local dev path uses the new `redis:7-alpine` service in
`docker-compose.yml`; AWS prod sources `REDIS_URL` from Secrets Manager.
Tests override the layer back to `InMemoryChannelLayer` in
`config/settings/test.py`.

Raising the ECS desired count above 1 is now safe from a channel-layer
correctness standpoint, but is still a separate operational step (with
canary + soak) independent of the code deploy that lands this change.

See also:
- `docs/learnings/channels-websocket-auth.md` — ASGI session-cookie auth
  middleware for WebSocket handshakes.
- `docs/learnings/redis-presence-hash.md` — Redis HASH presence pattern
  and debounced `last_seen_at` writer.
```

(Keep the rest of the file — Problem, Root Cause, Fix / Key Takeaway — as historical context so the original situation is traceable.)

- [ ] **Step 14.2: Create `docs/learnings/channels-websocket-auth.md`**

```markdown
# Learning: ASGI session-cookie auth for WebSocket handshakes

**Date**: 2026-04-09
**Context**: `apps/common/channels_auth.py`. Phase 3 multi-player consumer.
**Status**: Active

## Problem

Channels' WebSocket handshake does not run Django's HTTP middleware
stack. A consumer that reads `self.scope['user']` with no explicit auth
layer sees `AnonymousUser()` even when the client's browser has a valid
Django session cookie. This caught us in Plan 1A — see
`docs/learnings/iap-websocket-coverage.md`.

In Phase 3 we have the added wrinkle that ace-web runs behind the
shared connect-labs ALB under `/ace/` with a tenant-specific session
cookie name (`sessionid_ace`) to avoid colliding with scout / the
connect-labs tenant on the same host.

## Fix

`apps.common.channels_auth.AceSessionAuthMiddleware` wraps the
WebSocket URL router in `config/asgi.py`. On each handshake it:

1. Parses the `cookie` header out of `scope['headers']`.
2. Reads `settings.SESSION_COOKIE_NAME` (tenant-specific —
   `sessionid_ace` on AWS, `sessionid` in dev).
3. Loads the Django session row and runs `django.contrib.auth.get_user`
   inside a `sync_to_async` wrapper to resolve the user.
4. Sets `scope['user']` before delegating to the inner app.

The consumer's `connect()` then checks `scope['user'].is_authenticated`
and closes with code `4001` if not; it also pulls the
`SessionParticipant` row for the `(session, user)` pair and closes with
`4003` if the user is not a participant.

## Key Takeaway

When a project uses a non-default session cookie name, a hand-rolled
ASGI middleware that reads `settings.SESSION_COOKIE_NAME` is more
reliable than Channels' own `AuthMiddlewareStack`, which resolves the
cookie name in ways that can surprise you across upgrade paths. The
wrapper is thin (~50 lines) and entirely testable with a fake ASGI
scope — no live server needed.
```

- [ ] **Step 14.3: Create `docs/learnings/redis-presence-hash.md`**

```markdown
# Learning: Redis HASH presence with debounced Postgres writes

**Date**: 2026-04-09
**Context**: `apps/sessions/presence.py`. Phase 3 multi-player presence.
**Status**: Active

## Problem

Presence ("who is currently in this session") has two requirements that
pull in opposite directions:

1. Fast, cross-task — every ECS task needs to know the same answer in
   near real time so broadcast payloads are consistent.
2. Durable enough for the session library — `SessionParticipant.last_seen_at`
   must reflect "last time this user was in this session" for the
   session list page that lands in Phase 4.

Hitting Postgres on every heartbeat (one per user per 20s per session)
generates churn that does not scale, and storing live presence in
Postgres lags by the debounce window.

## Fix

A single Redis HASH per session, field = `str(user_id)`, value =
`str(expires_at_epoch_seconds)`:

    HSET presence:{session_slug} {user_id} {now + 60}

- `touch` is one `HSET`; returns True if the field was newly created
  so the consumer can broadcast `presence.joined` exactly once.
- `leave` is one `HDEL`; broadcast `presence.left`.
- `snapshot` does `HGETALL` and lazily `HDEL`s expired fields on read,
  so a crashed client ages out within one `snapshot` call ~60s after
  its last heartbeat.
- `is_present` is one `HGET` with a live/expired check.

No background sweeper task is needed. All state lives in one hash per
session.

The Postgres debounce uses a separate Redis key:

    SET presence.last_seen:{slug}:{user_id} 1 EX 30 NX

`NX` means "succeed only if the key does not exist." When it succeeds,
write `SessionParticipant.last_seen_at = now()`; when it fails, skip.
This is atomic across ECS tasks: only one task writes the DB row per
30s window, even if two heartbeats from different tasks race.

## Key Takeaway

A HASH with value-is-expiry beats per-user keys with native TTLs for
this kind of workload. It's one key per session (cheap cleanup on
session teardown), uses O(1) write per heartbeat, and the lazy sweep
on read is a natural fit for the access pattern (every read already
iterates the hash to build the presence list).

For DB debouncing across distributed processes, Redis `SET NX EX` is
the simplest atomic primitive — avoid reaching for advisory locks or
a "lease service."
```

- [ ] **Step 14.4: Update `CLAUDE.md`**

Open `CLAUDE.md` and make the following edits:

1. In the `## Current status` phase table, change the Phase 3 row:

```markdown
| 3     | Multi-player collaboration | WebSocket consumer, channels-redis, ASGI auth, drafts, presence                 | **Done** — per `docs/plans/2026-04-09-3-multi-player.md` |
```

2. In the `## Learnings` section, under `Infra & scaling:`, update the channels-single-instance bullet and add the two new learnings:

```markdown
Infra & scaling:
- [channels-single-instance](docs/learnings/channels-single-instance.md) — resolved in Phase 3; `CHANNEL_LAYERS` now uses channels-redis against shared ElastiCache. Raising ECS desired count past 1 is a separate operational step.
- [redis-presence-hash](docs/learnings/redis-presence-hash.md) — HASH-per-session presence + `SET NX EX` debounced Postgres writes for `last_seen_at`.
- [channels-websocket-auth](docs/learnings/channels-websocket-auth.md) — ASGI session-cookie middleware for WebSocket handshakes; tenant-specific cookie name.
```

3. In the `## What does NOT ship yet` section, remove the first bullet about WebSocket / drafts / presence (it now ships). Add a note under `## Key architectural decisions` that the chat transport is WebSocket-only as of Phase 3.

- [ ] **Step 14.5: Commit**

```bash
git add docs/learnings/channels-single-instance.md docs/learnings/channels-websocket-auth.md docs/learnings/redis-presence-hash.md CLAUDE.md
git commit -m "docs(phase-3): mark channels-single-instance resolved; add presence + auth learnings"
```

---

## Task 15: End-to-end smoke test and final suite run

**Files:** (none modified)

- [ ] **Step 15.1: Run the full backend test suite**

Run: `pytest -v`
Expected: all tests green. Count should include the new test files from Tasks 1–10. There should be no references to `apps.sessions.streaming` or `test_streaming.py`.

- [ ] **Step 15.2: Run ruff**

Run: `ruff check .`
Expected: clean. Fix any new warnings inline.

- [ ] **Step 15.3: Build the frontend**

Run: `cd frontend && bun run build`
Expected: clean build, no type errors or warnings.

- [ ] **Step 15.4: End-to-end smoke test with docker-compose**

In one terminal:

```bash
docker compose up -d db redis
docker compose run --rm app python manage.py migrate
docker compose up app
```

In a browser, open two different `@dimagi.com` sessions (two browser profiles, or two incognito windows after logging in with each account). Go through the flow:

1. Create a new session as Alice.
2. Use "Add teammate" → add Bob by email. Expect 201.
3. Bob opens the same `/chat/<slug>` URL. Expect his window to load the session and show a presence chip for Alice; Alice's window should show a new chip for Bob within a few seconds.
4. Alice types a prompt; Bob's window shows the body live updating.
5. Alice clicks Send. Both windows show the assistant response streaming token-by-token from the same source.
6. Bob clicks Stop mid-stream. Both windows show the message marked `error` with a `cancelled` detail.
7. Close Alice's browser tab. Bob's window should drop Alice's presence chip within ~60 s (or immediately on clean close).
8. Alice reconnects. Her window should show the full history including the cancelled response, and she should rejoin as a present user.

- [ ] **Step 15.5: Verify Redis state (optional diagnostic)**

```bash
docker compose exec redis redis-cli HGETALL presence:<slug>
```

You should see one field per currently-connected user with a numeric expires_at ~60 s in the future.

- [ ] **Step 15.6: Tear down**

```bash
docker compose down
```

- [ ] **Step 15.7: Final commit if any smoke-test fixes landed**

If the smoke test uncovered issues, fix them in-place with small commits (one fix per commit). Do not batch.

---

## Rollout notes (post-merge, operational)

These are NOT part of the plan's task list — they are actions the operator takes after the plan's PR merges:

1. Merge the PR via the normal flow.
2. Trigger the `deploy-labs.yml` GitHub Actions workflow with `run_migrations: false` (no schema changes). Confirm the `REDIS_URL` secret resolves at task start (check CloudWatch logs).
3. Dogfood the flow for ~30 minutes across two @dimagi.com accounts while the ECS desired count is still 1. If anything is off, roll back.
4. Raise ECS desired count to 2 via a separate task-definition bump. Verify presence replication by opening two browser sessions that land on different tasks (if possible — otherwise confirm via CloudWatch that the second task's logs show presence.joined events originating from the first task).
5. Update `docs/learnings/channels-single-instance.md` Status line from "Resolved in Phase 3" to "Resolved and scaled" with the date of the desired-count bump.

---

## References

- Phase 3 design spec: `docs/specs/2026-04-09-phase-3-multi-player-design.md`
- Whole-vision spec: `docs/specs/2026-04-08-ace-web-design.md` (§4.3, §5.2, §5.3)
- Phase 2 plan (source of the lifted turn driver code): `docs/plans/2026-04-08-2-conversation-engine.md`
- Existing learnings: `docs/learnings/channels-single-instance.md`, `docs/learnings/sse-django-async.md`, `docs/learnings/cli-stream-json-format.md`
