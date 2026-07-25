"""apps.canopy — the thin identity-brokering surface for canopy hosted chat."""

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

User = get_user_model()

pytestmark = pytest.mark.django_db

ENABLED = dict(CANOPY_BASE_URL="http://canopy.test", CANOPY_APP_CREDENTIAL="secret-cred")


def _login(client):
    # Mirrors the pattern used across the repo's api tests (see
    # apps/auth/tests/test_api.py, apps/activity/tests/test_api.py):
    # create_user + force_login against a Client/pytest-django client fixture.
    user = User.objects.create_user(email="chatter@example.com")
    client.force_login(user)
    return user


def test_status_disabled_by_default():
    c = Client()
    _login(c)
    body = c.get("/api/canopy/status").json()
    assert body["enabled"] is False


@override_settings(**ENABLED)
def test_status_enabled_and_shapes():
    c = Client()
    _login(c)
    body = c.get("/api/canopy/status").json()
    assert body == {
        "enabled": True,
        "base_url": "/canopy",
        "workspace": "connect",
        "agent": "ace",
    }


@override_settings(**ENABLED)
def test_token_exchanges_for_request_user():
    c = Client()
    user = _login(c)
    exchanged = {"token": "t", "expires_at": "x"}
    with mock.patch("apps.canopy.client.exchange_token", return_value=exchanged) as ex:
        r = c.post("/api/canopy/token")
    assert r.status_code == 200
    assert r.json()["token"] == "t"
    ex.assert_called_once_with(user.email, ttl=3600)


def test_token_503_when_disabled():
    c = Client()
    _login(c)
    assert c.post("/api/canopy/token").status_code == 503


def test_token_401_when_anonymous():
    c = Client()
    assert c.post("/api/canopy/token").status_code == 401


@override_settings(**ENABLED)
def test_session_create_forwards_metadata_with_user_token():
    c = Client()
    _login(c)
    user_token = {"token": "usertok", "expires_at": "x"}
    with (
        mock.patch("apps.canopy.client.exchange_token", return_value=user_token),
        mock.patch("apps.canopy.client.create_session", return_value={"id": "abc"}) as cs,
    ):
        r = c.post(
            "/api/canopy/sessions",
            data={"title": "T", "opp_slug": "field-hep"},
            content_type="application/json",
        )
    assert r.status_code == 200
    assert r.json()["id"] == "abc"
    kwargs = cs.call_args.kwargs
    assert cs.call_args.args[0] == "usertok"
    assert kwargs["metadata"] == {"source": "ace-web", "opp_slug": "field-hep"}
    assert kwargs["title"] == "T"
