import time
from unittest.mock import patch

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
