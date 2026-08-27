"""Tests for GET/PATCH /api/me/presence-preference.

Registered as a top-level router (see apps/api/api.py) with ace-web's
standard `session_auth` — the brief's inline router snippet omitted auth
entirely, which would ship unauthenticated endpoints and fail
`test_requires_authentication` below.
"""
import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(client):
    u = get_user_model().objects.create_user(email="p@x.com", display_name="P")
    client.force_login(u)
    return u


def test_defaults_to_visible(client, user):
    response = client.get("/api/me/presence-preference")
    assert response.status_code == 200
    assert response.json() == {"show_presence": True}


def test_opting_out_persists(client, user):
    patch = client.patch(
        "/api/me/presence-preference",
        data={"show_presence": False},
        content_type="application/json",
    )
    assert patch.status_code == 200
    assert patch.json() == {"show_presence": False}
    assert client.get("/api/me/presence-preference").json() == {"show_presence": False}


def test_opting_back_in_persists(client, user):
    client.patch(
        "/api/me/presence-preference",
        data={"show_presence": False},
        content_type="application/json",
    )
    client.patch(
        "/api/me/presence-preference",
        data={"show_presence": True},
        content_type="application/json",
    )
    assert client.get("/api/me/presence-preference").json() == {"show_presence": True}


def test_requires_authentication(client):
    assert client.get("/api/me/presence-preference").status_code in (401, 403)
