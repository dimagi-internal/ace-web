"""Tests for the App Home tab view builder + event dispatcher."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.slack.models import (
    SlackInstallation,
    SlackRunThread,
    SlackUserLink,
)
from apps.slack.tests.test_verify import SECRET, _sign
from apps.workspaces.models import Workspace

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def installation(db):
    owner = User.objects.create(email="owner@dimagi.com")
    ws = Workspace.objects.create(
        slug="dimagi-team", display_name="Dimagi",
        drive_root_folder_id="f", created_by=owner,
    )
    inst = SlackInstallation.objects.create(
        slack_team_id="T123", slack_team_name="Acme",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=owner,
    )
    inst.bot_token = "xoxb-test"
    inst.save()
    return inst, owner, ws


@pytest.fixture
def linked_user(installation):
    inst, _, _ = installation
    user = User.objects.create(email="member@dimagi.com")
    link = SlackUserLink.objects.create(
        installation=inst, slack_user_id="U_MEMBER", ace_user=user,
        slack_email="member@dimagi.com",
    )
    return link, user


# ---------------------------------------------------------------------------
# render_unlinked_view
# ---------------------------------------------------------------------------


def test_unlinked_view_has_link_button(installation):
    inst, _, _ = installation
    from apps.slack.home_view import render_unlinked_view
    view = render_unlinked_view(installation=inst, slack_user_id="U_NEW")
    assert view["type"] == "home"
    serialized = repr(view)
    assert "Link account" in serialized
    assert "/auth/slack/link/" in serialized


# ---------------------------------------------------------------------------
# render_linked_view
# ---------------------------------------------------------------------------


def test_linked_view_empty_tracked_runs(installation, linked_user):
    inst, _, _ = installation
    link, _ = linked_user
    from apps.slack.home_view import render_linked_view
    with patch("apps.slack.home_view._activity_lines", return_value=[]):
        view = render_linked_view(installation=inst, user_link=link)
    serialized = repr(view)
    assert "Linked as" in serialized
    assert "member@dimagi.com" in serialized
    assert "Your tracked runs* (0)" in serialized
    assert "aren't tracking any runs" in serialized


def test_linked_view_shows_tracked_runs(installation, linked_user):
    inst, _, _ = installation
    link, user = linked_user
    SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="111.222",
        opp_slug="rural-tb", run_id="run-001", ace_user=user,
    )
    from apps.slack.home_view import render_linked_view
    with patch("apps.slack.home_view._activity_lines", return_value=[]):
        view = render_linked_view(installation=inst, user_link=link)
    serialized = repr(view)
    assert "Your tracked runs* (1)" in serialized
    assert "rural-tb" in serialized
    # Channel link uses Slack's <#C1> mrkdwn so the channel name renders.
    assert "<#C1>" in serialized


def test_linked_view_includes_activity_when_present(installation, linked_user):
    inst, _, _ = installation
    link, _ = linked_user
    from apps.slack.home_view import render_linked_view
    with patch(
        "apps.slack.home_view._activity_lines",
        return_value=["• *<https://x/op1|opp-1>* · `r1` · _2m ago_"],
    ):
        view = render_linked_view(installation=inst, user_link=link)
    serialized = repr(view)
    assert "Workspace activity" in serialized
    assert "opp-1" in serialized


def test_linked_view_quick_action_buttons_point_to_workspace(installation, linked_user):
    inst, _, _ = installation
    link, _ = linked_user
    from apps.slack.home_view import render_linked_view
    with patch("apps.slack.home_view._activity_lines", return_value=[]):
        view = render_linked_view(installation=inst, user_link=link)
    serialized = repr(view)
    assert "/w/dimagi-team/opps" in serialized
    assert "/w/dimagi-team/activity" in serialized
    assert "/w/dimagi-team/workspace-settings" in serialized


# ---------------------------------------------------------------------------
# publish_for_user dispatch logic
# ---------------------------------------------------------------------------


def test_publish_for_user_publishes_linked_view_for_linked_user(
    installation, linked_user,
):
    inst, _, _ = installation
    link, _ = linked_user
    from apps.slack import home_view
    with patch.object(home_view, "render_linked_view",
                      return_value={"type": "home", "blocks": []}) as mock_linked, \
         patch("apps.slack.slack_client.SlackClient.views_publish") as mock_pub:
        ok = home_view.publish_for_user(
            team_id="T123", slack_user_id="U_MEMBER",
        )
    assert ok is True
    mock_linked.assert_called_once()
    mock_pub.assert_called_once()
    assert mock_pub.call_args.kwargs["user_id"] == "U_MEMBER"


def test_publish_for_user_publishes_unlinked_view_for_new_user(installation):
    inst, _, _ = installation
    from apps.slack import home_view
    with patch.object(home_view, "render_unlinked_view",
                      return_value={"type": "home", "blocks": []}) as mock_unlinked, \
         patch("apps.slack.slack_client.SlackClient.views_publish") as mock_pub:
        ok = home_view.publish_for_user(
            team_id="T123", slack_user_id="U_NEW_USER",
        )
    assert ok is True
    mock_unlinked.assert_called_once()
    mock_pub.assert_called_once()


def test_publish_for_user_returns_false_for_unknown_team(db):
    from apps.slack.home_view import publish_for_user
    assert publish_for_user(team_id="T_UNKNOWN", slack_user_id="U") is False


# ---------------------------------------------------------------------------
# events.py:app_home_opened wiring
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(SLACK_SIGNING_SECRET=SECRET)
def test_events_route_dispatches_app_home_opened(installation, linked_user):
    """The signed events webhook should call publish_for_user with the
    payload's team_id + event.user when type=app_home_opened."""
    import json as _json
    body = _json.dumps({
        "type": "event_callback",
        "team_id": "T123",
        "event": {"type": "app_home_opened", "user": "U_MEMBER", "tab": "home"},
    }).encode()
    ts = str(int(time.time()))
    sig = _sign(body, ts)
    with patch("apps.slack.home_view.publish_for_user") as mock_pub:
        c = Client()
        resp = c.post(
            "/api/slack/events", data=body,
            content_type="application/json",
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts, HTTP_X_SLACK_SIGNATURE=sig,
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_pub.assert_called_once_with(team_id="T123", slack_user_id="U_MEMBER")


@pytest.mark.django_db
@override_settings(SLACK_SIGNING_SECRET=SECRET)
def test_events_route_ignores_non_home_events():
    """Other event types (message, app_mention, etc.) just 200 and don't
    fan out to publish_for_user."""
    import json as _json
    body = _json.dumps({
        "type": "event_callback",
        "team_id": "T123",
        "event": {"type": "message", "user": "U_X", "text": "hello"},
    }).encode()
    ts = str(int(time.time()))
    sig = _sign(body, ts)
    with patch("apps.slack.home_view.publish_for_user") as mock_pub:
        c = Client()
        resp = c.post(
            "/api/slack/events", data=body,
            content_type="application/json",
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts, HTTP_X_SLACK_SIGNATURE=sig,
        )
    assert resp.status_code == 200
    mock_pub.assert_not_called()
