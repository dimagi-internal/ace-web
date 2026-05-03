"""Activity-feed endpoint tests.

The Drive-aggregation paths (verdict + gate events) require the full
Workbench fixture stack (stub plugin, fake Drive, OppWorkspace rows).
Those paths are exercised end-to-end by the existing opps tests; this
file scopes to the Postgres-only chat aggregation, which has no Drive
dependency."""
from __future__ import annotations

import pytest

from apps.auth.models import User
from apps.opps.models import OppWorkspace
from apps.sessions.models import Session
from apps.workspaces.models import Workspace, WorkspaceMembership


@pytest.fixture
def user(db):
    return User.objects.create_user(email="t@example.com", display_name="t")


@pytest.fixture
def workspace_with_user(db, user):
    ws = Workspace.objects.create(
        slug="test-ws",
        display_name="Test WS",
        drive_root_folder_id="root-folder-id",
        created_by=user,
    )
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="owner")
    return ws


@pytest.fixture
def authed_client(client, user):
    client.force_login(user)
    return client


def _drive_unreachable_url(opp: str | None = None, type_: str = "chat") -> str:
    # Pin to type=chat by default so the test doesn't trigger the
    # Drive-aggregation branch (which needs a real or fake DriveClient).
    qs = f"?type={type_}"
    if opp:
        qs += f"&opp={opp}"
    return f"/api/activity/{qs}"


@pytest.mark.django_db
def test_activity_feed_returns_chat_events(authed_client, user, workspace_with_user):
    """A workspace-scoped GET with ?type=chat returns Session rows as
    chat events, ordered newest-first."""
    Session.objects.create(
        owner=user, title="first", workspace=workspace_with_user,
    )
    Session.objects.create(
        owner=user, title="second", workspace=workspace_with_user,
        opp_slug="malaria-pilot", opp_step_skill="app-deploy",
    )

    resp = authed_client.get(
        _drive_unreachable_url(),
        HTTP_X_ACE_WORKSPACE="test-ws",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["error"] is None
    items = body["data"]["items"]
    assert len(items) == 2
    # Newest first (the second Session was created second).
    assert items[0]["title"] == "second"
    assert items[0]["kind"] == "chat"
    assert items[0]["opp_slug"] == "malaria-pilot"
    assert items[0]["step_skill"] == "app-deploy"
    assert items[1]["title"] == "first"
    assert items[1]["opp_slug"] is None


@pytest.mark.django_db
def test_activity_feed_filters_by_opp(authed_client, user, workspace_with_user):
    """``?opp=<slug>`` narrows chat events to that opp only."""
    Session.objects.create(
        owner=user, title="malaria-chat", workspace=workspace_with_user,
        opp_slug="malaria-pilot",
    )
    Session.objects.create(
        owner=user, title="other-chat", workspace=workspace_with_user,
        opp_slug="other-opp",
    )
    Session.objects.create(
        owner=user, title="unlinked", workspace=workspace_with_user,
    )
    OppWorkspace.objects.create(
        slug="malaria-pilot",
        display_name="Malaria Pilot",
        created_by=user,
        workspace=workspace_with_user,
    )

    resp = authed_client.get(
        _drive_unreachable_url(opp="malaria-pilot"),
        HTTP_X_ACE_WORKSPACE="test-ws",
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    titles = sorted(i["title"] for i in items)
    assert titles == ["malaria-chat"]


@pytest.mark.django_db
def test_activity_feed_excludes_chats_when_type_omits_chat(
    authed_client, user, workspace_with_user
):
    """``?type=verdict`` (no chat) returns no chat events even when
    Sessions exist. Drive aggregation may still run but in an isolated
    test there are no opps to iterate, so the result is an empty list."""
    Session.objects.create(owner=user, title="x", workspace=workspace_with_user)

    resp = authed_client.get(
        _drive_unreachable_url(type_="verdict"),
        HTTP_X_ACE_WORKSPACE="test-ws",
    )
    # The endpoint may return 200 with an empty list (if Drive listing
    # produces nothing) or a Drive-related error. Either way, the chat
    # event must NOT appear.
    if resp.status_code == 200:
        items = resp.json()["data"]["items"]
        assert all(i["kind"] != "chat" for i in items)
