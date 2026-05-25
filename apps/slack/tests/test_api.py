"""Contract tests for apps.slack.api (workspace-scoped endpoints).

Covers /status, /channels, /push-info, /push-phase across the four
relevant identity states (non-member, member, can-manage, install-missing)
and the two write paths (success + already-tracked conflict).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.slack.models import SlackInstallation, SlackRunThread
from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(db):
    owner = User.objects.create(email="owner@dimagi.com")
    ws = Workspace.objects.create(
        slug="test-ws", display_name="Test", drive_root_folder_id="f",
        created_by=owner,
    )
    WorkspaceMembership.objects.create(workspace=ws, user=owner, role="owner")
    return ws, owner


@pytest.fixture
def installed_workspace(workspace):
    ws, owner = workspace
    inst = SlackInstallation.objects.create(
        slack_team_id="T123", slack_team_name="Acme Slack",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=owner,
    )
    inst.bot_token = "xoxb-test"
    inst.save()
    return ws, owner, inst


@pytest.fixture
def member_client(db, client, workspace):
    ws, _ = workspace
    user = User.objects.create(email="member@dimagi.com")
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="editor")
    client.force_login(user)
    return client, user


@pytest.fixture
def stranger_client(db, client):
    user = User.objects.create(email="stranger@example.com")
    client.force_login(user)
    return client, user


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


def test_status_returns_not_installed_when_no_installation(member_client, workspace):
    client, _ = member_client
    resp = client.get("/api/w/test-ws/slack/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["installed"] is False
    # Non-dimagi-ai member does not get install URL nor can_manage.
    assert body.get("can_manage") is False
    assert "install_url" not in body  # exclude_none=True


def test_status_returns_404_for_non_member(stranger_client, installed_workspace):
    client, _ = stranger_client
    resp = client.get("/api/w/test-ws/slack/status")
    # Existence hidden — 404, not 403.
    assert resp.status_code == 404


def test_status_returns_installed_state(member_client, installed_workspace):
    client, _ = member_client
    with patch("apps.slack.api._ensure_team_url", return_value="https://acme.slack.com/"):
        resp = client.get("/api/w/test-ws/slack/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["installed"] is True
    assert body["team_id"] == "T123"
    assert body["team_name"] == "Acme Slack"
    assert body["team_url"] == "https://acme.slack.com/"
    assert body["installed_by_email"] == "owner@dimagi.com"
    assert "installed_at" in body
    assert body["test_page_url"].endswith("/api/slack/test/")


def test_status_can_manage_user_sees_install_url(db, client, installed_workspace):
    """Users with global write permission (dimagi-ai bot or staff) see the
    install URL so they can reconnect. Regular members don't."""
    ws, _, _ = installed_workspace
    bot = User.objects.create(email="ace@dimagi-ai.com")
    WorkspaceMembership.objects.create(workspace=ws, user=bot, role="editor")
    client.force_login(bot)
    with patch("apps.slack.api._ensure_team_url", return_value=""):
        resp = client.get("/api/w/test-ws/slack/status")
    body = resp.json()
    assert body["can_manage"] is True
    assert body["install_url"].endswith("/api/slack/install")


# ---------------------------------------------------------------------------
# GET /channels
# ---------------------------------------------------------------------------


def test_channels_returns_empty_when_not_installed(member_client, workspace):
    client, _ = member_client
    resp = client.get("/api/w/test-ws/slack/channels")
    assert resp.status_code == 200
    assert resp.json() == {"installed": False, "channels": []}


def test_channels_lists_member_channels(member_client, installed_workspace):
    client, _ = member_client
    fake_channels = [
        {"id": "C1", "name": "general", "is_private": False},
        {"id": "C2", "name": "ace-runs", "is_private": False},
    ]
    with patch(
        "apps.slack.slack_client.SlackClient.list_member_conversations",
        return_value=fake_channels,
    ):
        resp = client.get("/api/w/test-ws/slack/channels")
    assert resp.status_code == 200
    body = resp.json()
    assert body["installed"] is True
    assert [c["id"] for c in body["channels"]] == ["C1", "C2"]
    assert "error" not in body  # exclude_none on success path


def test_channels_surfaces_missing_scope_error(member_client, installed_workspace):
    """When Slack rejects conversations.list with missing_scope (typical
    after a bot-scope bump until the install is refreshed), the endpoint
    must surface `error` + a reinstall `hint` — NOT silently return
    `channels: []` which renders identically to 'bot isn't in any
    channels yet'."""
    from slack_sdk.errors import SlackApiError
    from slack_sdk.web import SlackResponse

    client, _ = member_client
    fake_resp = SlackResponse(
        client=None, http_verb="POST", api_url="x", req_args={},
        data={"ok": False, "error": "missing_scope",
              "needed": "channels:read,groups:read"},
        headers={}, status_code=200,
    )
    with patch(
        "apps.slack.slack_client.SlackClient.list_member_conversations",
        side_effect=SlackApiError("missing_scope", fake_resp),
    ):
        resp = client.get("/api/w/test-ws/slack/channels")
    assert resp.status_code == 200
    body = resp.json()
    assert body["installed"] is True
    assert body["channels"] == []
    assert body["error"] == "missing_scope"
    assert "channels:read" in body["hint"]
    assert "Reconnect" in body["hint"]


def test_channels_surfaces_generic_slack_error(member_client, installed_workspace):
    """Non-missing_scope Slack errors get a generic hint, not silently
    masked as 'no channels'."""
    from slack_sdk.errors import SlackApiError
    from slack_sdk.web import SlackResponse

    client, _ = member_client
    fake_resp = SlackResponse(
        client=None, http_verb="POST", api_url="x", req_args={},
        data={"ok": False, "error": "ratelimited"},
        headers={}, status_code=429,
    )
    with patch(
        "apps.slack.slack_client.SlackClient.list_member_conversations",
        side_effect=SlackApiError("ratelimited", fake_resp),
    ):
        resp = client.get("/api/w/test-ws/slack/channels")
    body = resp.json()
    assert body["error"] == "ratelimited"
    assert "ratelimited" in body["hint"]


# ---------------------------------------------------------------------------
# GET /push-info
# ---------------------------------------------------------------------------


def test_push_info_returns_empty_threads_when_none(member_client, installed_workspace):
    client, _ = member_client
    resp = client.get(
        "/api/w/test-ws/slack/push-info?opp=my-opp&run=run-001",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["installed"] is True
    assert body["threads"] == []


def test_push_info_lists_existing_threads(member_client, installed_workspace):
    client, _ = member_client
    _, owner, inst = installed_workspace
    SlackRunThread.objects.create(
        installation=inst, channel_id="C99", parent_ts="111.222",
        opp_slug="my-opp", run_id="run-001", ace_user=owner,
    )
    with patch(
        "apps.slack.slack_client.SlackClient.get_permalink",
        return_value="https://acme.slack.com/archives/C99/p111222",
    ):
        with patch("apps.slack.api._ensure_team_url", return_value=""):
            resp = client.get(
                "/api/w/test-ws/slack/push-info?opp=my-opp&run=run-001",
            )
    body = resp.json()
    assert len(body["threads"]) == 1
    t = body["threads"][0]
    assert t["channel_id"] == "C99"
    assert t["parent_ts"] == "111.222"
    assert t["permalink"].endswith("p111222")


def test_push_info_excludes_stopped_threads(member_client, installed_workspace):
    """Stopped threads are not active mirrors — UI shouldn't render them
    as 'Tracked in #foo' rows."""
    from django.utils import timezone

    client, _ = member_client
    _, owner, inst = installed_workspace
    SlackRunThread.objects.create(
        installation=inst, channel_id="C99", parent_ts="111.222",
        opp_slug="my-opp", run_id="run-001", ace_user=owner,
        stopped_at=timezone.now(),
    )
    resp = client.get(
        "/api/w/test-ws/slack/push-info?opp=my-opp&run=run-001",
    )
    body = resp.json()
    assert body["threads"] == []


# ---------------------------------------------------------------------------
# POST /push-phase
# ---------------------------------------------------------------------------


_FAKE_SNAPSHOT = {
    "display_name": "My Opp",
    "current_run": {
        "run_id": "run-001",
        "steps": [
            {"phase": "idea-to-design", "skill_name": "draft", "status": "complete",
             "ordinal": 0},
        ],
        "decisions": [],
    },
    "phases": [
        {"name": "idea-to-design", "display_name": "Idea→Design", "ordinal": 1},
    ],
}


def test_push_phase_404_when_not_installed(member_client, workspace):
    client, _ = member_client
    resp = client.post(
        "/api/w/test-ws/slack/push-phase",
        data={"opp_slug": "my-opp", "run_id": "run-001",
              "phase": "idea-to-design", "channel_id": "C1"},
        content_type="application/json",
    )
    assert resp.status_code == 404
    body = resp.json()
    assert "not installed" in body["title"].lower()


def test_push_phase_400_when_phase_unknown(member_client, installed_workspace):
    client, _ = member_client
    with patch("apps.slack.api._load_snapshot", return_value=_FAKE_SNAPSHOT):
        resp = client.post(
            "/api/w/test-ws/slack/push-phase",
            data={"opp_slug": "my-opp", "run_id": "run-001",
                  "phase": "bogus-phase", "channel_id": "C1"},
            content_type="application/json",
        )
    assert resp.status_code == 400


def test_push_phase_creates_thread_on_success(member_client, installed_workspace):
    client, user = member_client
    _, _, inst = installed_workspace
    with patch("apps.slack.api._load_snapshot", return_value=_FAKE_SNAPSHOT), \
         patch("apps.slack.slack_client.SlackClient.post_message",
               return_value="222.333") as mock_post, \
         patch("apps.slack.slack_client.SlackClient.get_permalink",
               return_value=None), \
         patch("apps.slack.api._ensure_team_url",
               return_value="https://acme.slack.com/"):
        resp = client.post(
            "/api/w/test-ws/slack/push-phase",
            data={"opp_slug": "my-opp", "run_id": "run-001",
                  "phase": "idea-to-design", "channel_id": "C1"},
            content_type="application/json",
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["channel_id"] == "C1"
    assert body["parent_ts"] == "222.333"
    # Constructed permalink fallback.
    assert body["permalink"].endswith("/archives/C1/p222333")

    # SlackRunThread created and linked to caller.
    thread = SlackRunThread.objects.get(opp_slug="my-opp", run_id="run-001")
    assert thread.channel_id == "C1"
    assert thread.parent_ts == "222.333"
    assert thread.source == "push"
    assert thread.ace_user_id == user.id

    # Two post_message calls: parent + phase tile (as thread reply).
    assert mock_post.call_count == 2
    second_kwargs = mock_post.call_args_list[1].kwargs
    assert second_kwargs.get("thread_ts") == "222.333"


def test_push_phase_400_when_bot_not_in_channel(member_client, installed_workspace):
    from apps.slack.slack_client import SlackChannelGone

    client, _ = member_client
    with patch("apps.slack.api._load_snapshot", return_value=_FAKE_SNAPSHOT), \
         patch("apps.slack.slack_client.SlackClient.post_message",
               side_effect=SlackChannelGone("not_in_channel")):
        resp = client.post(
            "/api/w/test-ws/slack/push-phase",
            data={"opp_slug": "my-opp", "run_id": "run-001",
                  "phase": "idea-to-design", "channel_id": "C_NOT_IN"},
            content_type="application/json",
        )
    assert resp.status_code == 400
    assert "invite" in resp.json()["title"].lower()


def test_push_phase_409_when_already_tracked_in_same_channel(
    member_client, installed_workspace,
):
    client, _ = member_client
    _, owner, inst = installed_workspace
    SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="000.001",
        opp_slug="my-opp", run_id="run-001", ace_user=owner,
    )
    with patch("apps.slack.api._load_snapshot", return_value=_FAKE_SNAPSHOT):
        resp = client.post(
            "/api/w/test-ws/slack/push-phase",
            data={"opp_slug": "my-opp", "run_id": "run-001",
                  "phase": "idea-to-design", "channel_id": "C1"},
            content_type="application/json",
        )
    assert resp.status_code == 409
