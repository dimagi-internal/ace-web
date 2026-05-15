# apps/slack/tests/test_views_auth.py
import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.slack.models import SlackInstallation, SlackUserLink
from apps.slack.pending import save_pending_command
from apps.workspaces.models import Workspace


@pytest.fixture
def setup_installation(db):
    User = get_user_model()
    admin = User.objects.create(email="admin@dimagi.com")
    ws = Workspace.objects.create(slug="dimagi-team", display_name="Dimagi Team",
                                  drive_root_folder_id="f", created_by=admin)
    inst = SlackInstallation.objects.create(
        slack_team_id="T1", slack_team_name="Dimagi",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=admin,
    )
    inst.bot_token = "xoxb-1"; inst.save()
    return inst, admin


@pytest.mark.django_db
def test_link_route_creates_user_link_and_replays(setup_installation):
    inst, admin = setup_installation
    User = get_user_model()
    jj = User.objects.create(email="jj@dimagi.com")
    jj.set_password("pw"); jj.save()

    nonce = save_pending_command(slack_user_id="U_JJ", team_id="T1",
                                 channel_id="C1", command_text="/ace help")

    from unittest.mock import patch
    with patch("apps.slack.views_auth._replay_command") as replay:
        replay.return_value = None
        c = Client()
        c.force_login(jj)
        resp = c.get(f"/auth/slack/link/?nonce={nonce}")
    assert resp.status_code == 200
    assert SlackUserLink.objects.filter(
        installation=inst, slack_user_id="U_JJ", ace_user=jj,
    ).exists()
    replay.assert_called_once()


@pytest.mark.django_db
def test_link_route_requires_login(setup_installation):
    nonce = save_pending_command(slack_user_id="U_JJ", team_id="T1",
                                 channel_id="C1", command_text="/ace help")
    c = Client()
    resp = c.get(f"/auth/slack/link/?nonce={nonce}")
    # Should redirect to Connect login.
    assert resp.status_code in (302, 401)


@pytest.mark.django_db
def test_link_route_rejects_unknown_nonce(setup_installation):
    User = get_user_model()
    jj = User.objects.create(email="jj@dimagi.com")
    c = Client()
    c.force_login(jj)
    resp = c.get("/auth/slack/link/?nonce=nope")
    assert resp.status_code == 400
