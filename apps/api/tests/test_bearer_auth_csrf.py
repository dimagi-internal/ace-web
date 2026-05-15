"""Regression tests for Bearer-token CSRF bypass on Ninja endpoints.

DjangoSessionAuth extends ninja's SessionAuth (APIKeyCookie), whose default
``_get_key`` runs a CSRF check before ``authenticate()``.  Without the override
in apps/api/auth.py, POST/PUT/PATCH/DELETE requests carrying only an
``Authorization: Bearer <pat>`` header are rejected with 403 before the Bearer
code path runs — exactly what /ace:run's transcript upload observed.
"""
from __future__ import annotations

import pytest
from django.test import Client

from apps.auth.models import PersonalToken

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="bearer-csrf@example.com", display_name="bearer-csrf"
    )


@pytest.fixture
def bearer_token(user) -> str:
    raw, _ = PersonalToken.create_for_user(user=user, label="test")
    return raw


def test_bearer_post_with_csrf_enforced_is_not_blocked(bearer_token):
    """POST + Bearer header + no CSRF token → must reach the view, not 403.

    Uses ``/api/auth/logout`` as a minimal session_auth-protected POST.  We
    only care that we don't get a CSRF 403 — a 200 (or any non-403 auth
    outcome) proves the Bearer path executed.
    """
    api = Client(enforce_csrf_checks=True)
    response = api.post(
        "/api/auth/logout",
        HTTP_AUTHORIZATION=f"Bearer {bearer_token}",
    )
    assert response.status_code != 403, (
        f"Bearer POST hit CSRF middleware: {response.status_code} {response.content!r}"
    )
    assert response.status_code in {200, 204}


def test_bearer_post_with_invalid_token_returns_401_not_403(user):
    """An invalid Bearer token should fall through to authenticate() and
    raise 401 — not be short-circuited to 403 by the CSRF check."""
    api = Client(enforce_csrf_checks=True)
    response = api.post(
        "/api/auth/logout",
        HTTP_AUTHORIZATION="Bearer not-a-real-token",
    )
    assert response.status_code == 401, (
        f"expected 401 from authenticate(); got {response.status_code} {response.content!r}"
    )


def test_session_post_without_csrf_token_still_blocked(user):
    """Cookie-only session callers must still be CSRF-checked on unsafe
    methods.  The Bearer bypass must not weaken session auth."""
    api = Client(enforce_csrf_checks=True)
    api.force_login(user)
    response = api.post("/api/auth/logout")  # no CSRF token, no Bearer header
    assert response.status_code == 403
