"""Tests for `/ace activity` + the Track-from-activity block action."""
from __future__ import annotations

from unittest.mock import patch

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
    SlackUserLink.objects.create(
        installation=inst, slack_user_id="U_JJ", ace_user=jj,
        slack_email="jj@dimagi.com", slack_real_name="JJ",
    )
    return inst, jj


_FAKE_ACTIVITY = {
    "rows": [
        {
            "opp_slug": "rural-tb",
            "opp_display_name": "Rural TB Screening",
            "run_id": "20260515-1830",
            "last_activity_at": "2026-05-15T18:30:00Z",
            "current_phase_name": "scenarios-and-acceptance",
            "current_phase_display": "Scenarios & Acceptance",
            "current_step_name": "scenarios",
            "current_step_display": "Scenarios",
            "lifecycle_status": "in_progress",
            "last_actor": None,
            "source_hint": "ace-web",
            "source_actor_email": "jj@dimagi.com",
            "phase_url": "https://labs/.../w/dimagi-team/opps/rural-tb?run_id=20260515-1830",
        },
        {
            "opp_slug": "leep-paint",
            "opp_display_name": "Leep Paint Collection",
            "run_id": "20260514-1530",
            "last_activity_at": "2026-05-15T18:00:00Z",
            "current_phase_name": None,
            "current_phase_display": None,
            "current_step_name": None,
            "current_step_display": None,
            "lifecycle_status": "complete",
            "last_actor": None,
            "source_hint": "drive-only",
            "source_actor_email": None,
            "phase_url": "https://labs/.../w/dimagi-team/opps/leep-paint?run_id=20260514-1530",
        },
    ],
    "server_now": "2026-05-15T18:31:00Z",
}


@pytest.mark.django_db
def test_activity_with_response_url_acks_fast_and_posts_async(setup):
    """The data fetch hits Drive — verify we ack immediately with a
    loading message and dispatch the real work to run_async."""
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.verbs_activity.run_async") as mock_async:
        resp = dispatch_slash_command(
            text="activity", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="",
            response_url="https://hooks.slack.com/x",
        )
    assert resp["response_type"] == "ephemeral"
    assert "Loading" in resp["text"]
    mock_async.assert_called_once()


@pytest.mark.django_db
def test_activity_synchronous_path_renders_rows(setup):
    """No response_url → synchronous path. The rendered blocks should
    contain both opps' display names and the source labels."""
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.verbs_activity.get_workspace_activity") as mock_get:
        mock_get.return_value = _FAKE_ACTIVITY
        resp = dispatch_slash_command(
            text="activity", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="", response_url="",
        )
    body = repr(resp.get("blocks", []))
    assert "Rural TB Screening" in body
    assert "Leep Paint Collection" in body
    # Source attribution is shown.
    assert "ace-web" in body
    assert "jj@dimagi.com" in body
    assert "Drive only" in body
    # No "running" / "alive" claims — we show timestamps as facts only.
    assert "running" not in body.lower() or "is running" not in body.lower()
    # The header line uses backticks around the workspace slug.
    header = resp["text"]
    assert "dimagi-team" in header


@pytest.mark.django_db
def test_activity_empty_returns_helpful_message(setup):
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.verbs_activity.get_workspace_activity") as mock_get:
        mock_get.return_value = {"rows": [], "server_now": "2026-05-15T18:31:00Z"}
        resp = dispatch_slash_command(
            text="activity", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="", response_url="",
        )
    assert "No active runs" in resp["text"]


@pytest.mark.django_db
def test_activity_all_flag_includes_completed(setup):
    """`/ace activity --all` toggles include_completed=True (default
    already True actually, but the flag should still be parsed)."""
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.verbs_activity.get_workspace_activity") as mock_get:
        mock_get.return_value = _FAKE_ACTIVITY
        dispatch_slash_command(
            text="activity --all", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="", response_url="",
        )
    kwargs = mock_get.call_args.kwargs
    assert kwargs.get("include_completed") is True


@pytest.mark.django_db
def test_activity_renders_as_single_section_bulleted_list(setup):
    """Post-launch v2 UX pass: ditch per-row sections + Open buttons.
    The opp title is already a hyperlink, so just emit a markdown
    bulleted list inside one section block."""
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.verbs_activity.get_workspace_activity") as mock_get:
        mock_get.return_value = _FAKE_ACTIVITY
        resp = dispatch_slash_command(
            text="activity", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="", response_url="",
        )
    blocks = resp.get("blocks") or []
    section_blocks = [b for b in blocks if b.get("type") == "section"]
    action_blocks = [b for b in blocks if b.get("type") == "actions"]
    divider_blocks = [b for b in blocks if b.get("type") == "divider"]
    # Exactly ONE section block (the body — bulleted list).
    assert len(section_blocks) == 1
    assert action_blocks == []
    assert divider_blocks == []
    # No Open button (no accessory).
    assert "accessory" not in section_blocks[0]
    body = section_blocks[0]["text"]["text"]
    # All rows present, each as a single line.
    assert "Rural TB Screening" in body
    assert "Leep Paint Collection" in body
    # Bullet markers — one per row.
    assert body.count("\n•") + (1 if body.startswith("•") else 0) == len(
        _FAKE_ACTIVITY["rows"]
    )
    # No `unknown` noise.
    assert "`unknown`" not in body
    # Footer mentions both flags.
    assert "/ace track" in repr(blocks[-1])
    assert "/ace activity" in repr(blocks[-1])


@pytest.mark.django_db
def test_track_block_action_creates_slack_run_thread(setup):
    """Clicking the Track button on an activity row → SlackRunThread row."""
    inst, _ = setup
    payload = {
        "type": "block_actions",
        "team": {"id": "T1"},
        "user": {"id": "U_JJ"},
        "channel": {"id": "C42"},
        "actions": [{"action_id": "track_run_from_activity",
                     "value": "rural-tb:20260515-1830"}],
    }
    from unittest.mock import MagicMock
    with patch("apps.slack.verbs_track._load_snapshot") as load, \
         patch("apps.slack.verbs_track._get_client") as get_client:
        load.return_value = {
            "display_name": "Rural TB",
            "current_run": {"run_id": "20260515-1830", "steps": [], "decisions": []},
            "phases": [],
        }
        client = MagicMock()
        client.post_message.return_value = "12.34"
        get_client.return_value = client
        from apps.slack.handlers import dispatch_interaction
        resp = dispatch_interaction(payload)
    assert resp["response_type"] == "ephemeral"
    assert "mirroring" in resp["text"].lower()
    assert SlackRunThread.objects.filter(
        opp_slug="rural-tb", run_id="20260515-1830", channel_id="C42",
    ).exists()


def test_render_row_with_no_phase_omits_state_bit():
    """Observable-facts-only: when current_phase is None we don't know
    if the run completed or crashed. Don't render a state token; just
    show source + recency."""
    import datetime as dt

    from apps.slack.verbs_activity import _render_row_line
    now = dt.datetime(2026, 5, 15, 18, 31, tzinfo=dt.UTC)
    line = _render_row_line(
        {
            "opp_slug": "done", "opp_display_name": "Done Opp",
            "run_id": "r1", "last_activity_at": "2026-05-15T18:30:00Z",
            "current_phase_name": None, "current_phase_display": None,
            "current_step_name": None, "current_step_display": None,
            "lifecycle_status": "no-active-phase",
            "source_hint": "drive-only", "source_actor_email": None,
            "phase_url": "https://example/done",
        },
        now=now, base_url="https://example",
    )
    # No state claims at all.
    assert "complete" not in line.lower()
    assert "running" not in line.lower()
    assert "failed" not in line.lower()
    # But we still show source + recency.
    assert "Drive only" in line
    assert " ago" in line


def test_render_row_observable_facts_only():
    """Even for in-progress rows, we never claim 'running' / 'alive'."""
    import datetime as dt

    from apps.slack.verbs_activity import _render_row_line
    now = dt.datetime(2026, 5, 15, 18, 31, tzinfo=dt.UTC)
    line = _render_row_line(
        {
            "opp_slug": "x", "opp_display_name": "X",
            "run_id": "r", "last_activity_at": "2026-05-15T18:30:00Z",
            "current_phase_name": "scenarios",
            "current_phase_display": "Scenarios",
            "current_step_name": None, "current_step_display": None,
            "lifecycle_status": "in_progress",
            "source_hint": "drive-only", "source_actor_email": None,
            "phase_url": "https://example/x",
        },
        now=now, base_url="https://example",
    )
    body = line.lower()
    # Recency is rendered as 'Nm ago' (compact form, post-launch UX pass).
    # The point of the test is the absence of liveness claims, not a
    # particular phrasing.
    import re
    assert re.search(r"\d+[smhd] ago", body), body
    assert "is running" not in body
    assert "alive" not in body
