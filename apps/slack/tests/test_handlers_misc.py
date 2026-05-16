# apps/slack/tests/test_handlers_misc.py
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.slack.models import SlackInstallation, SlackUserLink
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
    inst.bot_token = "xoxb-1"
    inst.save()
    jj = User.objects.create(email="jj@dimagi.com")
    SlackUserLink.objects.create(installation=inst, slack_user_id="U_JJ",
                                 ace_user=jj, slack_email="jj@dimagi.com",
                                 slack_real_name="JJ")
    return inst, jj


@pytest.mark.django_db
def test_help_returns_ephemeral_usage(setup):
    from apps.slack.handlers import dispatch_slash_command
    resp = dispatch_slash_command(
        text="help", slack_user_id="U_JJ", team_id="T1", channel_id="C1",
        trigger_id="", response_url="",
    )
    assert resp["response_type"] == "ephemeral"
    assert "/ace run" in resp["text"]


@pytest.mark.django_db
def test_unknown_subcommand_returns_help(setup):
    from apps.slack.handlers import dispatch_slash_command
    resp = dispatch_slash_command(
        text="banana", slack_user_id="U_JJ", team_id="T1", channel_id="C1",
        trigger_id="", response_url="",
    )
    assert resp["response_type"] == "ephemeral"
    assert "Usage" in resp["text"] or "/ace help" in resp["text"]


@pytest.mark.django_db
def test_unlinked_user_gets_link_in_ephemeral(setup):
    """Unlinked users get the OAuth-link URL inline in an ephemeral, not via
    a DM (DMs would require im:write scope and an extra Slack API call —
    ephemerals are equally private and instant)."""
    from apps.slack.handlers import dispatch_slash_command
    resp = dispatch_slash_command(
        text="run my-opp", slack_user_id="U_UNKNOWN",
        team_id="T1", channel_id="C1", trigger_id="", response_url="",
    )
    assert resp["response_type"] == "ephemeral"
    assert "/auth/slack/link" in resp["text"] or any(
        "/auth/slack/link" in repr(b) for b in (resp.get("blocks") or [])
    )


@pytest.mark.django_db
def test_link_subcommand_returns_link_in_ephemeral(setup):
    from apps.slack.handlers import dispatch_slash_command
    resp = dispatch_slash_command(
        text="link", slack_user_id="U_JJ", team_id="T1", channel_id="C1",
        trigger_id="", response_url="",
    )
    assert resp["response_type"] == "ephemeral"
    assert "/auth/slack/link" in resp["text"] or any(
        "/auth/slack/link" in repr(b) for b in (resp.get("blocks") or [])
    )


@pytest.mark.django_db
def test_link_url_does_not_double_script_name_prefix(setup):
    """Regression guard: ACE_PUBLIC_BASE_URL already includes the /ace
    script-name prefix, and reverse() also prepends it under
    FORCE_SCRIPT_NAME. We hardcode the path to avoid /ace/ace/... dupes."""
    from django.test import override_settings
    with override_settings(
        ACE_PUBLIC_BASE_URL="https://labs.connect.dimagi.com/ace",
        FORCE_SCRIPT_NAME="/ace",
    ):
        from apps.slack.handlers import dispatch_slash_command
        resp = dispatch_slash_command(
            text="link", slack_user_id="U_JJ", team_id="T1", channel_id="C1",
            trigger_id="", response_url="",
        )
    body = resp.get("text", "") + repr(resp.get("blocks", []))
    assert "/ace/ace/" not in body
    assert "/ace/auth/slack/link/" in body


@pytest.mark.django_db
def test_status_returns_parent_card_for_user_recent_run(setup):
    inst, jj = setup
    from apps.slack.models import SlackRunThread
    SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="1.1",
        opp_slug="my-opp", run_id="run-001", ace_user=jj,
    )
    with patch("apps.slack.verbs_query._load_snapshot") as load:
        load.return_value = {
            "display_name": "My Opp",
            "current_run": {"run_id": "run-001", "steps": [], "decisions": []},
            "phases": [],
        }
        from apps.slack.handlers import dispatch_slash_command
        resp = dispatch_slash_command(
            text="status", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="", response_url="",
        )
    assert resp["response_type"] == "ephemeral"
    assert "My Opp" in repr(resp.get("blocks", [])) or "My Opp" in resp.get("text", "")


@pytest.mark.django_db
def test_status_with_no_runs_returns_message(setup):
    from apps.slack.handlers import dispatch_slash_command
    resp = dispatch_slash_command(
        text="status", slack_user_id="U_JJ", team_id="T1",
        channel_id="C1", trigger_id="", response_url="",
    )
    assert resp["response_type"] == "ephemeral"
    assert "no active runs" in resp["text"].lower()


@pytest.mark.django_db
def test_list_runs_shows_user_tracked_runs(setup):
    inst, jj = setup
    from apps.slack.models import SlackRunThread
    for i in range(3):
        SlackRunThread.objects.create(
            installation=inst, channel_id=f"C{i}", parent_ts=f"{i}.0",
            opp_slug=f"opp-{i}", run_id="run-001", ace_user=jj,
        )
    from apps.slack.handlers import dispatch_slash_command
    resp = dispatch_slash_command(
        text="list runs", slack_user_id="U_JJ", team_id="T1",
        channel_id="C1", trigger_id="", response_url="",
    )
    assert resp["response_type"] == "ephemeral"
    body = repr(resp.get("blocks", [])) + resp.get("text", "")
    assert "opp-0" in body and "opp-1" in body and "opp-2" in body


@pytest.mark.django_db
def test_list_runs_with_no_runs_returns_message(setup):
    from apps.slack.handlers import dispatch_slash_command
    resp = dispatch_slash_command(
        text="list runs", slack_user_id="U_JJ", team_id="T1",
        channel_id="C1", trigger_id="", response_url="",
    )
    assert resp["response_type"] == "ephemeral"
    assert "no active" in resp["text"].lower()


@pytest.mark.django_db
def test_list_opps_shows_workspace_opps(setup):
    """Bare `/ace list` AND `/ace list opps` both show workspace opps."""
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.verbs_query.list_opp_cards") as mock_cards:
        mock_cards.return_value = [
            {"slug": "rural-tb", "title": "Rural TB Screening",
             "current_phase": "scenarios-and-acceptance",
             "current_skill": "scenarios", "run_count": 2,
             "updated_at": "2026-05-15T20:00:00Z"},
            {"slug": "leep-paint", "title": "Leep Paint Collection",
             "current_phase": "idea-to-design", "current_skill": None,
             "run_count": 1, "updated_at": "2026-05-14T15:00:00Z"},
        ]
        resp = dispatch_slash_command(
            text="list opps", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="", response_url="",
        )
    assert resp["response_type"] == "ephemeral"
    body = resp["text"]
    assert "Rural TB Screening" in body
    assert "rural-tb" in body
    assert "Leep Paint" in body
    assert "scenarios-and-acceptance" in body


@pytest.mark.django_db
def test_list_bare_falls_back_to_opps(setup):
    """`/ace list` without an arg defaults to opps (people usually want that)."""
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.verbs_query.list_opp_cards") as mock_cards:
        mock_cards.return_value = [
            {"slug": "rural-tb", "title": "Rural TB", "current_phase": "p",
             "run_count": 1, "updated_at": "2026-05-15T20:00:00Z"},
        ]
        resp = dispatch_slash_command(
            text="list", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="", response_url="",
        )
    assert "rural-tb" in resp["text"]
    assert "Rural TB" in resp["text"]


@pytest.mark.django_db
def test_list_opps_with_no_opps_returns_message(setup):
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.verbs_query.list_opp_cards") as mock_cards:
        mock_cards.return_value = []
        resp = dispatch_slash_command(
            text="list opps", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="", response_url="",
        )
    assert resp["response_type"] == "ephemeral"
    assert "No opps" in resp["text"]
    assert "/ace new" in resp["text"]


@pytest.mark.django_db
def test_list_opps_falls_back_to_status_when_no_current_phase(setup):
    """A completed run has no current_phase but does have status. The
    rendering should show the status (e.g. 'complete') instead of '—'."""
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.verbs_query.list_opp_cards") as mock_cards:
        mock_cards.return_value = [
            {"slug": "done-opp", "title": "Finished Opp",
             "current_phase": None, "status": "complete",
             "run_count": 3, "updated_at": "2026-05-15T20:00:00Z"},
            {"slug": "running-opp", "title": "Running Opp",
             "current_phase": "scenarios", "status": "running",
             "run_count": 1, "updated_at": "2026-05-15T19:00:00Z"},
        ]
        resp = dispatch_slash_command(
            text="list opps", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="", response_url="",
        )
    body = resp["text"]
    # The completed opp shows "complete" (its status), not the phase dash.
    assert "Finished Opp" in body
    assert "complete" in body
    # The running opp shows its in-progress phase.
    assert "scenarios" in body


@pytest.mark.django_db
def test_list_runs_with_slug_shows_all_runs_from_drive(setup):
    """`/ace list runs <slug>` reads from Drive (not just Slack-tracked
    threads) so it surfaces runs other people started."""
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.verbs_query.list_opp_runs_for_workspace") as mock_runs:
        mock_runs.return_value = [
            {"run_id": "20260515-1500", "lifecycle_status": "complete",
             "current_phase": None, "latest_phase_done": "ocs-setup",
             "latest_phase_done_display": "OCS Setup",
             "is_active": False, "started_at": "2026-05-15T15:00:00Z"},
            {"run_id": "20260515-1800", "lifecycle_status": "in_progress",
             "current_phase": "scenarios-and-acceptance",
             "current_phase_display": "Scenarios & Acceptance",
             "is_active": True, "started_at": "2026-05-15T18:00:00Z"},
        ]
        resp = dispatch_slash_command(
            text="list runs leep-paint-collection", slack_user_id="U_JJ",
            team_id="T1", channel_id="C1", trigger_id="", response_url="",
        )
    mock_runs.assert_called_once()
    body = resp["text"]
    assert "20260515-1500" in body
    assert "20260515-1800" in body
    # Active run gets the running marker; complete run gets the check.
    assert "🟡" in body and "✅" in body


@pytest.mark.django_db
def test_list_runs_with_slug_empty_returns_message(setup):
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.verbs_query.list_opp_runs_for_workspace") as mock_runs:
        mock_runs.return_value = []
        resp = dispatch_slash_command(
            text="list runs nonexistent", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="", response_url="",
        )
    assert "No runs" in resp["text"]


@pytest.mark.django_db
def test_list_opps_with_response_url_acks_fast_and_posts_async(setup):
    """When Slack provides a response_url, we ack within 3s and POST the
    real list to response_url in a background thread. Verifies the ack
    is the loading message and run_async was called with _list_opps."""
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.verbs_query.run_async") as mock_async:
        resp = dispatch_slash_command(
            text="list opps", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="",
            response_url="https://hooks.slack.com/commands/T1/123/abc",
        )
    assert "Loading" in resp["text"]
    assert resp["response_type"] == "ephemeral"
    mock_async.assert_called_once()
    args = mock_async.call_args
    assert args.args[0] == "https://hooks.slack.com/commands/T1/123/abc"


@pytest.mark.django_db
def test_list_runs_with_slug_and_response_url_acks_fast(setup):
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.verbs_query.run_async") as mock_async:
        resp = dispatch_slash_command(
            text="list runs leep-paint", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="",
            response_url="https://hooks.slack.com/commands/T1/123/abc",
        )
    assert "Loading runs" in resp["text"]
    assert "leep-paint" in resp["text"]
    mock_async.assert_called_once()


@pytest.mark.django_db
def test_list_runs_no_slug_does_not_use_async(setup):
    """`/ace list runs` (your tracked runs) is a fast DB query — should
    NOT go through the async path (saves a background thread)."""
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.verbs_query.run_async") as mock_async:
        resp = dispatch_slash_command(
            text="list runs", slack_user_id="U_JJ", team_id="T1",
            channel_id="C1", trigger_id="",
            response_url="https://hooks.slack.com/commands/T1/123/abc",
        )
    mock_async.assert_not_called()
    # Synchronous response.
    assert resp["response_type"] == "ephemeral"
