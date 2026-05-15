# apps/slack/tests/test_install.py
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.workspaces.models import Workspace


@pytest.fixture
def admin_user(db):
    User = get_user_model()
    user = User.objects.create(email="admin@dimagi.com", is_staff=True,
                               is_superuser=True)
    user.set_password("pw")
    user.save()
    return user


@pytest.fixture
def dimagi_workspace(admin_user):
    return Workspace.objects.create(
        slug="dimagi-team", display_name="Dimagi Team",
        drive_root_folder_id="folder-1", created_by=admin_user,
    )


@pytest.mark.django_db
@override_settings(SLACK_CLIENT_ID="cid", SLACK_CLIENT_SECRET="secret")
def test_install_redirects_to_slack_oauth(admin_user, client: Client):
    client.force_login(admin_user)
    resp = client.get("/api/slack/install")
    assert resp.status_code == 302
    assert resp.url.startswith("https://slack.com/oauth/v2/authorize")
    assert "client_id=cid" in resp.url
    assert "scope=" in resp.url


@pytest.mark.django_db
@override_settings(SLACK_CLIENT_ID="cid", SLACK_CLIENT_SECRET="secret")
def test_oauth_callback_creates_installation(admin_user, dimagi_workspace,
                                             client: Client):
    client.force_login(admin_user)
    with patch("apps.slack.views._exchange_code") as exchange:
        exchange.return_value = {
            "ok": True,
            "team": {"id": "T0001", "name": "Dimagi"},
            "bot_user_id": "U_BOT",
            "access_token": "xoxb-secret",
        }
        resp = client.get("/api/slack/oauth/callback?code=abc123")
    assert resp.status_code == 200
    from apps.slack.models import SlackInstallation
    inst = SlackInstallation.objects.get(slack_team_id="T0001")
    assert inst.bot_token == "xoxb-secret"
    assert inst.ace_workspace == dimagi_workspace
