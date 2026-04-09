"""Tests for AceSessionAuthMiddleware — the ASGI middleware that reads
the `sessionid_ace` cookie from a WebSocket handshake scope and resolves
it to a Django User.

These tests do not spin up a full ASGI server. They construct a fake
scope dict and call the middleware directly, asserting the attached
scope['user'] via an inner mock app that records the scope it received.
"""
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore

from apps.common.channels_auth import AceSessionAuthMiddleware

pytestmark = pytest.mark.django_db(transaction=True)


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


def _build_session_for(user) -> str:
    """Create a Django session row that references `user` and return its key.

    Wrapped in sync_to_async by the caller — SessionStore.save() and
    get_session_auth_hash() both hit the DB and can't run inside an
    async test body directly.
    """
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    # Django auth also stores the backend path; AuthenticationMiddleware
    # uses it to reconstruct the user. We mirror it here.
    store["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    store["_auth_user_hash"] = user.get_session_auth_hash()
    store.save()
    return store.session_key


def _build_session_with_stale_hash(user):
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    store["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    # Deliberately wrong hash — simulates a password change after the
    # session was minted. get_user() should reject this.
    store["_auth_user_hash"] = "not-the-real-hash"
    store.save()
    return store


async def test_valid_session_key_attaches_user(user):
    session_key = await sync_to_async(_build_session_for)(user)

    scope = _scope_with_cookies({settings.SESSION_COOKIE_NAME: session_key})
    out = await _run_middleware(scope)
    assert out["user"].pk == user.pk
    assert out["user"].is_authenticated


async def test_stale_auth_hash_yields_anonymous_user(user):
    """If the user's password (or session-auth hash) changes after the
    session cookie was issued, django.contrib.auth.get_user must reject
    the session. Verify the middleware honors that rejection."""
    store = await sync_to_async(_build_session_with_stale_hash)(user)
    scope = _scope_with_cookies({settings.SESSION_COOKIE_NAME: store.session_key})
    out = await _run_middleware(scope)
    assert isinstance(out["user"], AnonymousUser)
