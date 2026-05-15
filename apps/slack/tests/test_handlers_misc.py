# apps/slack/tests/test_handlers_misc.py
from unittest.mock import patch, MagicMock

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
    inst.bot_token = "xoxb-1"; inst.save()
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
def test_unlinked_user_gets_dm_link(setup):
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.handlers._get_client") as get_client:
        mock = MagicMock(); get_client.return_value = mock
        resp = dispatch_slash_command(
            text="run my-opp", slack_user_id="U_UNKNOWN",
            team_id="T1", channel_id="C1", trigger_id="", response_url="",
        )
    mock.dm_user.assert_called_once()
    dm_kwargs = mock.dm_user.call_args.kwargs
    assert dm_kwargs["user"] == "U_UNKNOWN"
    assert "/auth/slack/link" in dm_kwargs["text"] or any(
        "/auth/slack/link" in repr(b) for b in (dm_kwargs.get("blocks") or [])
    )
    assert resp["response_type"] == "ephemeral"
    assert "link" in resp["text"].lower()


@pytest.mark.django_db
def test_link_subcommand_resends_link(setup):
    from apps.slack.handlers import dispatch_slash_command
    with patch("apps.slack.handlers._get_client") as get_client:
        mock = MagicMock(); get_client.return_value = mock
        resp = dispatch_slash_command(
            text="link", slack_user_id="U_JJ", team_id="T1", channel_id="C1",
            trigger_id="", response_url="",
        )
    mock.dm_user.assert_called_once()
    assert resp["response_type"] == "ephemeral"
