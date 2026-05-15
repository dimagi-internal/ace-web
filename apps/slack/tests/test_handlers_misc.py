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
def test_list_shows_user_runs(setup):
    inst, jj = setup
    from apps.slack.models import SlackRunThread
    for i in range(3):
        SlackRunThread.objects.create(
            installation=inst, channel_id=f"C{i}", parent_ts=f"{i}.0",
            opp_slug=f"opp-{i}", run_id="run-001", ace_user=jj,
        )
    from apps.slack.handlers import dispatch_slash_command
    resp = dispatch_slash_command(
        text="list", slack_user_id="U_JJ", team_id="T1",
        channel_id="C1", trigger_id="", response_url="",
    )
    assert resp["response_type"] == "ephemeral"
    body = repr(resp.get("blocks", [])) + resp.get("text", "")
    assert "opp-0" in body and "opp-1" in body and "opp-2" in body
