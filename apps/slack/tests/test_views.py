import time
from unittest.mock import patch
from urllib.parse import quote as _quote

import pytest
from django.test import Client, override_settings

from apps.slack.tests.test_verify import _sign, SECRET


@pytest.mark.django_db
@override_settings(SLACK_SIGNING_SECRET=SECRET)
def test_commands_rejects_unsigned():
    c = Client()
    resp = c.post("/api/slack/commands", data={"command": "/ace", "text": "help"})
    assert resp.status_code == 401


@pytest.mark.django_db
@override_settings(SLACK_SIGNING_SECRET=SECRET)
def test_commands_accepts_signed_request_and_dispatches():
    ts = str(int(time.time()))
    body = b"command=/ace&text=help&team_id=T1&user_id=U_JJ&channel_id=C1&trigger_id=tg1"
    sig = _sign(body, ts)
    with patch("apps.slack.handlers.dispatch_slash_command") as mock_dispatch:
        mock_dispatch.return_value = {"response_type": "ephemeral", "text": "ok"}
        c = Client()
        resp = c.post("/api/slack/commands", data=body,
                      content_type="application/x-www-form-urlencoded",
                      HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
                      HTTP_X_SLACK_SIGNATURE=sig)
    assert resp.status_code == 200
    assert resp.json() == {"response_type": "ephemeral", "text": "ok"}
    mock_dispatch.assert_called_once()
    call_kwargs = mock_dispatch.call_args.kwargs
    assert call_kwargs["text"] == "help"
    assert call_kwargs["slack_user_id"] == "U_JJ"


@pytest.mark.django_db
@override_settings(SLACK_SIGNING_SECRET=SECRET)
def test_fork_action_returns_ephemeral_deeplink():
    import json as _json
    payload = {
        "type": "block_actions",
        "team": {"id": "T1"},
        "user": {"id": "U_JJ"},
        "actions": [{"action_id": "fork_from_phase",
                     "value": "rural-tb:scenarios-and-acceptance"}],
    }
    body_form = "payload=" + _quote(_json.dumps(payload))
    ts = str(int(time.time()))
    sig = _sign(body_form.encode(), ts)
    # Need a SlackInstallation in dimagi-team workspace so the workspace
    # slug resolves.
    from django.contrib.auth import get_user_model
    User = get_user_model()
    admin = User.objects.create(email="admin@dimagi.com")
    from apps.workspaces.models import Workspace
    ws = Workspace.objects.create(slug="dimagi-team", display_name="Dimagi",
                                  drive_root_folder_id="f", created_by=admin)
    from apps.slack.models import SlackInstallation
    inst = SlackInstallation.objects.create(
        slack_team_id="T1", slack_team_name="Dimagi",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=admin,
    )
    inst.bot_token = "xoxb-1"; inst.save()

    c = Client()
    resp = c.post("/api/slack/interactions", data=body_form,
                  content_type="application/x-www-form-urlencoded",
                  HTTP_X_SLACK_REQUEST_TIMESTAMP=ts, HTTP_X_SLACK_SIGNATURE=sig)
    assert resp.status_code == 200
    body = resp.json()
    serialized = repr(body)
    assert "rural-tb" in serialized
    assert "fork=scenarios-and-acceptance" in serialized
    assert "dimagi-team" in serialized
