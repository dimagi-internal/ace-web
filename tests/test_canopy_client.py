"""apps.canopy — the thin identity-brokering surface for canopy hosted chat."""

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.workspaces.models import Workspace, WorkspaceMembership

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


def _member_client(slug="ws-a"):
    """A logged-in client that is a member of the given ace workspace."""
    c = Client()
    creator = User.objects.create_user(email=f"creator-{slug}@example.com")
    workspace = Workspace.objects.create(
        slug=slug, display_name=slug, drive_root_folder_id=f"folder-{slug}", created_by=creator,
    )
    user = User.objects.create_user(email=f"member-{slug}@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="editor")
    c.force_login(user)
    return c, workspace, user


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


@override_settings(**ENABLED)
def test_token_picks_fields_and_ignores_upstream_extras():
    """I4: CanopyTokenOut is a strict (extra='forbid') schema, so the handler
    must pick {token, expires_at} explicitly rather than passing canopy's raw
    response dict straight through — an extra field upstream must not 500
    every token mint on this end with no ace-web deploy involved."""
    c = Client()
    _login(c)
    exchanged = {"token": "t", "expires_at": "x", "some_new_upstream_field": "whatever"}
    with mock.patch("apps.canopy.client.exchange_token", return_value=exchanged):
        r = c.post("/api/canopy/token")
    assert r.status_code == 200
    assert r.json() == {"token": "t", "expires_at": "x"}


def test_token_503_when_disabled():
    c = Client()
    _login(c)
    assert c.post("/api/canopy/token").status_code == 503


def test_token_401_when_anonymous():
    c = Client()
    assert c.post("/api/canopy/token").status_code == 401


# ---------------------------------------------------------------------------
# Session create — now workspace-scoped (C1). Route moved from the flat
# /api/canopy/sessions to /api/w/{workspace_slug}/canopy/sessions so it
# reuses resolve_workspace_for_member's membership gate; origin_key is
# derived from that path parameter, never client input.
# ---------------------------------------------------------------------------


@override_settings(**ENABLED)
def test_session_create_forwards_metadata_with_user_token():
    c, workspace, _user = _member_client()
    user_token = {"token": "usertok", "expires_at": "x"}
    with (
        mock.patch("apps.canopy.client.exchange_token", return_value=user_token),
        mock.patch("apps.canopy.client.create_session", return_value={"id": "abc"}) as cs,
    ):
        r = c.post(
            f"/api/w/{workspace.slug}/canopy/sessions",
            data={"title": "T", "opp_slug": "field-hep"},
            content_type="application/json",
        )
    assert r.status_code == 200
    assert r.json()["id"] == "abc"
    kwargs = cs.call_args.kwargs
    assert cs.call_args.args[0] == "usertok"
    assert kwargs["metadata"] == {
        "source": "ace-web",
        "origin_key": f"ace-web:{workspace.slug}",
        "opp_slug": "field-hep",
    }
    assert kwargs["title"] == "T"


@override_settings(**ENABLED)
def test_session_create_rejects_a_client_supplied_origin_key():
    """C1: CanopySessionCreateIn (extra='forbid') has no origin_key/
    workspace_slug field at all — a client trying to smuggle one in the body
    gets a 422, never a silently-ignored-or-honored value."""
    c, workspace, _user = _member_client()
    with (
        mock.patch("apps.canopy.client.exchange_token") as ex,
        mock.patch("apps.canopy.client.create_session") as cs,
    ):
        r = c.post(
            f"/api/w/{workspace.slug}/canopy/sessions",
            data={"title": "T", "origin_key": "ace-web:some-other-workspace"},
            content_type="application/json",
        )
    assert r.status_code == 422
    ex.assert_not_called()
    cs.assert_not_called()


@override_settings(**ENABLED)
def test_session_create_non_member_404s():
    """C1: a caller who is not a member of the ace workspace in the URL gets
    404 (workspace existence hidden), matching resolve_workspace_for_member's
    convention used across every other workspace-scoped router — this is the
    fix for the cross-workspace chat exposure (a team-b user could otherwise
    mint a session origin_key'd to team-a by hitting team-a's slug)."""
    creator = User.objects.create_user(email="creator2@example.com")
    workspace = Workspace.objects.create(
        slug="ws-b", display_name="WS B", drive_root_folder_id="folder-b", created_by=creator,
    )
    c = Client()
    outsider = User.objects.create_user(email="outsider@example.com")
    c.force_login(outsider)
    with (
        mock.patch("apps.canopy.client.exchange_token") as ex,
        mock.patch("apps.canopy.client.create_session") as cs,
    ):
        r = c.post(
            f"/api/w/{workspace.slug}/canopy/sessions",
            data={"title": "T"},
            content_type="application/json",
        )
    assert r.status_code == 404
    ex.assert_not_called()
    cs.assert_not_called()


@override_settings(**ENABLED)
def test_session_create_unknown_workspace_404s():
    c = Client()
    _login(c)
    r = c.post(
        "/api/w/does-not-exist/canopy/sessions",
        data={"title": "T"},
        content_type="application/json",
    )
    assert r.status_code == 404


def test_session_create_anon_401():
    creator = User.objects.create_user(email="creator3@example.com")
    workspace = Workspace.objects.create(
        slug="ws-c", display_name="WS C", drive_root_folder_id="folder-c", created_by=creator,
    )
    c = Client()
    r = c.post(f"/api/w/{workspace.slug}/canopy/sessions", data={}, content_type="application/json")
    assert r.status_code == 401


def test_session_create_disabled_returns_503_for_a_member():
    c, workspace, _user = _member_client("ws-d")
    r = c.post(
        f"/api/w/{workspace.slug}/canopy/sessions",
        data={"title": "T"},
        content_type="application/json",
    )
    assert r.status_code == 503


@override_settings(**ENABLED)
def test_two_ace_workspaces_get_distinct_origin_keys():
    """C1: sessions created from two different ace workspaces must stamp
    distinct origin_key values, so canopy's ?origin_key= list filter
    actually separates them (the cross-workspace exposure this fixes)."""
    creator = User.objects.create_user(email="creator4@example.com")
    ws_a = Workspace.objects.create(
        slug="team-a", display_name="Team A", drive_root_folder_id="folder-ta", created_by=creator,
    )
    ws_b = Workspace.objects.create(
        slug="team-b", display_name="Team B", drive_root_folder_id="folder-tb", created_by=creator,
    )
    user = User.objects.create_user(email="dual-member@example.com")
    WorkspaceMembership.objects.create(workspace=ws_a, user=user, role="editor")
    WorkspaceMembership.objects.create(workspace=ws_b, user=user, role="editor")
    c = Client()
    c.force_login(user)

    seen_metadata = []
    user_token = {"token": "usertok", "expires_at": "x"}
    with (
        mock.patch("apps.canopy.client.exchange_token", return_value=user_token),
        mock.patch("apps.canopy.client.create_session") as cs,
    ):
        cs.side_effect = lambda *_a, **kw: (seen_metadata.append(kw["metadata"]) or {"id": "abc"})
        c.post(f"/api/w/{ws_a.slug}/canopy/sessions", data={}, content_type="application/json")
        c.post(f"/api/w/{ws_b.slug}/canopy/sessions", data={}, content_type="application/json")

    assert seen_metadata[0]["origin_key"] == "ace-web:team-a"
    assert seen_metadata[1]["origin_key"] == "ace-web:team-b"
    assert seen_metadata[0]["origin_key"] != seen_metadata[1]["origin_key"]
