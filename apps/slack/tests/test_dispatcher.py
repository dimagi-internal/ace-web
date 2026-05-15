# apps/slack/tests/test_dispatcher.py
from unittest.mock import patch, MagicMock

import pytest
from django.contrib.auth import get_user_model

from apps.slack.models import SlackInstallation, SlackRunThread
from apps.workspaces.models import Workspace


@pytest.fixture
def setup(db):
    User = get_user_model()
    admin = User.objects.create(email="admin@dimagi.com")
    ws = Workspace.objects.create(slug="dimagi-team", display_name="Dimagi",
                                  drive_root_folder_id="f", created_by=admin)
    inst = SlackInstallation.objects.create(
        slack_team_id="T1", slack_team_name="Dimagi",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=admin,
    )
    inst.bot_token = "xoxb-1"; inst.save()
    user = User.objects.create(email="jj@dimagi.com")
    return inst, user, ws


def _snap():
    return {
        "display_name": "My Opp",
        "current_run": {
            "run_id": "run-001",
            "steps": [
                {"phase": "idea-to-design", "skill_name": "draft", "status": "complete",
                 "ordinal": 0, "judge": {"score_pct": 80}},
            ],
            "decisions": [],
        },
        "phases": [
            {"name": "idea-to-design", "display_name": "Idea to Design",
             "agent": "i2d", "ordinal": 1},
        ],
    }


@pytest.mark.django_db
def test_dispatch_tick_posts_new_phase_message(setup):
    inst, user, ws = setup
    thread = SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="1.1",
        opp_slug="my-opp", run_id="run-001", ace_user=user,
    )
    with patch("apps.slack.dispatcher._load_snapshot") as load, \
         patch("apps.slack.dispatcher._get_client") as get_client:
        load.return_value = _snap()
        client = MagicMock(); get_client.return_value = client
        client.post_message.return_value = "2.0"
        from apps.slack.dispatcher import dispatch_tick
        dispatch_tick(thread_id=thread.pk)
    thread.refresh_from_db()
    assert "idea-to-design" in thread.phase_messages
    assert thread.phase_messages["idea-to-design"]["ts"] == "2.0"
    client.update_message.assert_called()  # parent card updated


@pytest.mark.django_db
def test_dispatch_tick_skips_unchanged_phase(setup):
    inst, user, ws = setup
    snap = _snap()
    from apps.slack.blocks import phase_state_hash
    h = phase_state_hash(snap, "idea-to-design")
    thread = SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="1.1",
        opp_slug="my-opp", run_id="run-001", ace_user=user,
        phase_messages={"idea-to-design": {"ts": "2.0", "last_state_hash": h}},
    )
    with patch("apps.slack.dispatcher._load_snapshot") as load, \
         patch("apps.slack.dispatcher._get_client") as get_client:
        load.return_value = snap
        client = MagicMock(); get_client.return_value = client
        from apps.slack.dispatcher import dispatch_tick
        dispatch_tick(thread_id=thread.pk)
    # No chat.update for the (unchanged) phase. Parent card may be updated
    # — but the phase tile must not be.
    for call in client.update_message.call_args_list:
        assert call.kwargs.get("ts") != "2.0"


@pytest.mark.django_db
def test_dispatch_tick_marks_broken_on_channel_gone(setup):
    inst, user, ws = setup
    thread = SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="1.1",
        opp_slug="my-opp", run_id="run-001", ace_user=user,
    )
    from apps.slack.slack_client import SlackChannelGone
    with patch("apps.slack.dispatcher._load_snapshot") as load, \
         patch("apps.slack.dispatcher._get_client") as get_client:
        load.return_value = _snap()
        client = MagicMock(); get_client.return_value = client
        client.post_message.side_effect = SlackChannelGone("channel_not_found")
        from apps.slack.dispatcher import dispatch_tick
        dispatch_tick(thread_id=thread.pk)
    thread.refresh_from_db()
    assert thread.broken_at is not None
