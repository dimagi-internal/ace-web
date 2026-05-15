# apps/slack/tests/test_handlers_run.py
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from apps.slack.models import (
    SlackInstallation,
    SlackRunThread,
    SlackUserLink,
)
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
    return inst, link, ws


@pytest.mark.django_db
def test_run_creates_thread_and_posts_parent_card(setup):
    inst, link, ws = setup
    with patch("apps.slack.verbs_run.start_run_from_slack") as start, \
         patch("apps.slack.verbs_run._get_client") as get_client:
        start.return_value = ("my-opp", "run-001")
        client = MagicMock()
        get_client.return_value = client
        client.post_message.return_value = "1.1"
        from apps.slack.verbs_run import handle_run
        resp = handle_run(
            installation=inst, user_link=link,
            rest="my-opp", channel_id="C1", trigger_id="tg",
        )

    assert resp["response_type"] == "ephemeral"
    assert "kicking off" in resp["text"].lower()
    start.assert_called_once()
    client.post_message.assert_called_once()
    thread = SlackRunThread.objects.get(opp_slug="my-opp", run_id="run-001")
    assert thread.channel_id == "C1"
    assert thread.parent_ts == "1.1"
    assert thread.ace_user_id == link.ace_user_id


@pytest.mark.django_db
def test_run_duplicate_returns_already_running(setup):
    inst, link, ws = setup
    SlackRunThread.objects.create(
        installation=inst, channel_id="C1", parent_ts="9.9",
        opp_slug="my-opp", run_id="run-001", ace_user=link.ace_user,
    )
    with patch("apps.slack.verbs_run.start_run_from_slack") as start, \
         patch("apps.slack.verbs_run._get_client") as get_client:
        # start should never be called for a duplicate
        start.side_effect = NotImplementedError(
            "should not have been called for duplicate"
        )
        with patch("apps.slack.verbs_run._lookup_active_run") as lookup:
            lookup.return_value = ("my-opp", "run-001")
            client = MagicMock()
            get_client.return_value = client
            from apps.slack.verbs_run import handle_run
            resp = handle_run(
                installation=inst, user_link=link,
                rest="my-opp", channel_id="C1", trigger_id="tg",
            )

    assert resp["response_type"] == "ephemeral"
    assert "already running" in resp["text"].lower()


@pytest.mark.django_db
def test_run_with_empty_slug_returns_usage(setup):
    inst, link, ws = setup
    from apps.slack.verbs_run import handle_run
    resp = handle_run(
        installation=inst, user_link=link,
        rest="", channel_id="C1", trigger_id="tg",
    )
    assert resp["response_type"] == "ephemeral"
    assert "/ace run" in resp["text"]
