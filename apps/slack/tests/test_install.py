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


@pytest.mark.django_db
@override_settings(SLACK_CLIENT_ID="cid", SLACK_CLIENT_SECRET="secret")
def test_install_allows_dimagi_ai_bot_identity(db, client: Client):
    """ace@dimagi-ai.com is the automation identity. It must be able to
    drive the install OAuth flow even though it's not is_staff. The old
    `_is_staff`-only gate locked it out AND fell into a redirect loop
    (user_passes_test redirects to login by default, login bounces back
    because the user IS authenticated). The fix: switch the gate to
    `_can_write_global` and raise_exception=True so failure is a clean
    403 instead of a redirect.
    """
    User = get_user_model()
    bot = User.objects.create(email="ace@dimagi-ai.com", is_staff=False)
    client.force_login(bot)
    resp = client.get("/api/slack/install")
    assert resp.status_code == 302
    assert resp.url.startswith("https://slack.com/oauth/v2/authorize")


@pytest.mark.django_db
@override_settings(SLACK_CLIENT_ID="cid", SLACK_CLIENT_SECRET="secret")
def test_install_returns_403_for_unprivileged_user(db, client: Client):
    """Regression guard for the redirect-loop bug. An authenticated user
    who can't manage Slack must get a 403, NOT a redirect to login —
    302→login produces an infinite loop when the user is already
    authenticated."""
    User = get_user_model()
    user = User.objects.create(email="someone@external.example", is_staff=False)
    client.force_login(user)
    resp = client.get("/api/slack/install")
    assert resp.status_code == 403, (
        "Must be 403, not 302 — 302 to /login produces an infinite redirect "
        "loop when the user is already authenticated."
    )
