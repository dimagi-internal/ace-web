"""Tests for `/ace track`, `/ace untrack`, and the Stop-watching block action."""
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from apps.slack.models import SlackInstallation, SlackRunThread, SlackUserLink
from apps.workspaces.models import Workspace


@pytest.fixture
def setup(db):
    User = get_user_model()
    admin = User.objects.create(email="admin@dimagi.com")
    ws = Workspace.objects.create(
        slug="dimagi-team", display_name="Dimagi",
        drive_root_folder_id="f", created_by=admin,
    )
    inst = SlackInstallation.objects.create(
        slack_team_id="T1", slack_team_name="Dimagi",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=admin,
    )
    inst.bot_token = "xoxb-1"
    inst.save()
    jj = User.objects.create(email="jj@dimagi.com")
    link = SlackUserLink.objects.create(
        installation=inst, slack_user_id="U_JJ", ace_user=jj,
        slack_email="jj@dimagi.com", slack_real_name="JJ",
    )
    return inst, link, jj


def _snap(run_id="20260515-1015"):
    return {
        "display_name": "Rural TB",
        "current_run": {
            "run_id": run_id,
            "steps": [
                {"phase": "idea-to-design", "skill_name": "draft",
                 "status": "running", "ordinal": 0, "judge": None},
            ],
            "decisions": [],
        },
        "phases": [{"name": "idea-to-design", "display_name": "Idea to Design",
                    "agent": "i2d", "ordinal": 1}],
    }


@pytest.mark.django_db
def test_track_defaults_to_current_run(setup):
    inst, link, _ = setup
    with patch("apps.slack.verbs_track._load_snapshot") as load, \
         patch("apps.slack.verbs_track._get_client") as get_client:
        load.return_value = _snap("20260515-1015")
        client = MagicMock()
        client.post_message.return_value = "1.1"
        get_client.return_value = client
        from apps.slack.verbs_track import handle_track
        resp = handle_track(installation=inst, user_link=link,
                            rest="rural-tb", channel_id="C1")
    assert resp["response_type"] == "ephemeral"
    assert "mirroring" in resp["text"].lower()
    thread = SlackRunThread.objects.get(opp_slug="rural-tb",
                                        run_id="20260515-1015")
    assert thread.channel_id == "C1"
    assert thread.parent_ts == "1.1"
    assert thread.source == "track"
    assert thread.stopped_at is None


@pytest.mark.django_db
def test_track_with_explicit_run_id(setup):
    inst, link, _ = setup
    with patch("apps.slack.verbs_track._load_snapshot") as load, \
         patch("apps.slack.verbs_track._get_client") as get_client:
        load.return_value = _snap("20260515-1015")
        client = MagicMock()
        client.post_message.return_value = "2.0"
        get_client.return_value = client
        from apps.slack.verbs_track import handle_track
        resp = handle_track(installation=inst, user_link=link,
                            rest="rural-tb/20260515-1015", channel_id="C1")
    assert resp["response_type"] == "ephemeral"
    # _load_snapshot called with the explicit run_id
    load.assert_called_once()
    assert load.call_args.kwargs["run_id"] == "20260515-1015"


@pytest.mark.django_db
def test_track_unknown_slug_returns_error(setup):
    inst, link, _ = setup
    with patch("apps.slack.verbs_track._load_snapshot") as load:
        load.return_value = None
        from apps.slack.verbs_track import handle_track
        resp = handle_track(installation=inst, user_link=link,
                            rest="nope", channel_id="C1")
    assert resp["response_type"] == "ephemeral"
    assert "No opp" in resp["text"]
    assert not SlackRunThread.objects.filter(opp_slug="nope").exists()


@pytest.mark.django_db
def test_track_empty_arg_returns_usage(setup):
    inst, link, _ = setup
    from apps.slack.verbs_track import handle_track
    resp = handle_track(installation=inst, user_link=link,
                        rest="", channel_id="C1")
    assert resp["response_type"] == "ephemeral"
    assert "/ace track" in resp["text"]


@pytest.mark.django_db
def test_track_duplicate_returns_existing_pointer(setup):
    inst, link, jj = setup
    SlackRunThread.objects.create(
        installation=inst, channel_id="C9", parent_ts="0.1",
        opp_slug="rural-tb", run_id="20260515-1015", ace_user=jj,
        source="track",
    )
    with patch("apps.slack.verbs_track._load_snapshot") as load:
        load.return_value = _snap("20260515-1015")
        from apps.slack.verbs_track import handle_track
        resp = handle_track(installation=inst, user_link=link,
                            rest="rural-tb", channel_id="C1")
    assert resp["response_type"] == "ephemeral"
    assert "already being tracked" in resp["text"]
    assert "C9" in resp["text"]
    # Should not have created a second active thread for this run.
    active = SlackRunThread.objects.filter(
        opp_slug="rural-tb", run_id="20260515-1015",
        stopped_at__isnull=True, broken_at__isnull=True,
    )
    assert active.count() == 1


@pytest.mark.django_db
def test_untrack_marks_stopped_at(setup):
    inst, link, jj = setup
    thread = SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="1.1",
        opp_slug="rural-tb", run_id="20260515-1015", ace_user=jj,
        source="track",
    )
    with patch("apps.slack.verbs_track._load_snapshot") as load, \
         patch("apps.slack.verbs_track._get_client") as get_client:
        load.return_value = _snap("20260515-1015")
        get_client.return_value = MagicMock()
        from apps.slack.verbs_track import handle_untrack
        resp = handle_untrack(installation=inst, user_link=link, rest="rural-tb")
    assert resp["response_type"] == "ephemeral"
    assert "Stopped" in resp["text"]
    thread.refresh_from_db()
    assert thread.stopped_at is not None
    assert thread.stopped_by_id == jj.pk


@pytest.mark.django_db
def test_untrack_unknown_slug_returns_error(setup):
    inst, link, _ = setup
    from apps.slack.verbs_track import handle_untrack
    resp = handle_untrack(installation=inst, user_link=link, rest="nope")
    assert resp["response_type"] == "ephemeral"
    assert "No active" in resp["text"]


@pytest.mark.django_db
def test_stop_watching_action_marks_thread_stopped(setup):
    inst, link, jj = setup
    thread = SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="1.1",
        opp_slug="rural-tb", run_id="20260515-1015", ace_user=jj,
        source="track",
    )
    payload = {
        "type": "block_actions",
        "team": {"id": "T1"},
        "user": {"id": "U_JJ"},
        "actions": [{"action_id": "stop_watching", "value": str(thread.pk)}],
    }
    with patch("apps.slack.verbs_track._load_snapshot") as load, \
         patch("apps.slack.verbs_track._get_client") as get_client:
        load.return_value = _snap("20260515-1015")
        get_client.return_value = MagicMock()
        from apps.slack.handlers import dispatch_interaction
        resp = dispatch_interaction(payload)
    assert resp["response_type"] == "ephemeral"
    assert "Stopped" in resp["text"]
    thread.refresh_from_db()
    assert thread.stopped_at is not None
    assert thread.stopped_by_id == jj.pk


@pytest.mark.django_db
def test_stop_watching_action_idempotent(setup):
    inst, _, jj = setup
    from django.utils import timezone
    thread = SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="1.1",
        opp_slug="rural-tb", run_id="r1", ace_user=jj,
        stopped_at=timezone.now(), stopped_by=jj,
    )
    payload = {
        "type": "block_actions",
        "team": {"id": "T1"},
        "user": {"id": "U_JJ"},
        "actions": [{"action_id": "stop_watching", "value": str(thread.pk)}],
    }
    from apps.slack.handlers import dispatch_interaction
    resp = dispatch_interaction(payload)
    assert resp["response_type"] == "ephemeral"
    assert "Already" in resp["text"]


@pytest.mark.django_db
def test_dispatch_tick_skips_stopped_threads(setup):
    inst, _, jj = setup
    from django.utils import timezone
    thread = SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="1.1",
        opp_slug="rural-tb", run_id="r1", ace_user=jj,
        stopped_at=timezone.now(), stopped_by=jj,
    )
    with patch("apps.slack.dispatcher._load_snapshot") as load, \
         patch("apps.slack.dispatcher._get_client") as get_client:
        load.return_value = _snap()
        client = MagicMock()
        get_client.return_value = client
        from apps.slack.dispatcher import dispatch_tick
        dispatch_tick(thread_id=thread.pk)
    client.post_message.assert_not_called()
    client.update_message.assert_not_called()
    load.assert_not_called()


def test_parent_card_includes_stop_button_when_thread_id_passed():
    from apps.slack.blocks import render_parent_card
    blocks = render_parent_card(
        _snap(), opp_slug="rural-tb", workspace_slug="dimagi-team",
        triggerer_display="<@U_JJ>", elapsed_seconds=60,
        thread_id="abc-123",
    )
    serialized = repr(blocks)
    assert "Stop watching" in serialized
    assert "stop_watching" in serialized
    assert "abc-123" in serialized


def test_parent_card_hides_stop_button_when_stopped():
    from apps.slack.blocks import render_parent_card
    blocks = render_parent_card(
        _snap(), opp_slug="rural-tb", workspace_slug="dimagi-team",
        triggerer_display="<@U_JJ>", elapsed_seconds=60,
        thread_id="abc-123",
        stopped_by_display="<@U_JJ>",
    )
    serialized = repr(blocks)
    assert "Stop watching" not in serialized
    assert "Stopped" in serialized
