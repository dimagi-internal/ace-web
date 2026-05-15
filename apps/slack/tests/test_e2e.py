# apps/slack/tests/test_e2e.py
"""End-to-end happy path: /ace run → SlackRunThread created → opp.updated
event → SlackOppConsumer dispatches → Slack chat.update called with a
phase tile."""
import time
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.slack.models import (
    SlackInstallation,
    SlackRunThread,
    SlackUserLink,
)
from apps.slack.tests.test_verify import SECRET, _sign
from apps.workspaces.models import Workspace


@pytest.mark.django_db
@override_settings(SLACK_SIGNING_SECRET=SECRET)
def test_run_to_phase_tile_happy_path():
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

    # 1. Slash command POST → signature verified → handler called →
    #    start_run_from_slack is mocked, but the dispatcher path is real.
    ts = str(int(time.time()))
    body = (b"command=/ace&text=run+rural-tb&team_id=T1&user_id=U_JJ"
            b"&channel_id=C1&trigger_id=tg1")
    sig = _sign(body, ts)

    snapshot = {
        "display_name": "Rural TB",
        "current_run": {
            "run_id": "run-001",
            "steps": [
                {"phase": "idea-to-design", "skill_name": "draft",
                 "status": "complete", "ordinal": 0,
                 "judge": {"score_pct": 80}},
            ],
            "decisions": [],
        },
        "phases": [{"name": "idea-to-design", "display_name": "Idea to Design",
                    "agent": "i2d", "ordinal": 1}],
    }

    with patch("apps.slack.verbs_run.start_run_from_slack") as start, \
         patch("apps.slack.dispatcher._load_snapshot") as load, \
         patch("apps.slack.slack_client.WebClient") as web_cls:
        start.return_value = ("rural-tb", "run-001")
        load.return_value = snapshot
        web_inst = web_cls.return_value
        web_inst.chat_postMessage.return_value = {"ok": True, "ts": "1.1"}
        web_inst.chat_update.return_value = {"ok": True}

        c = Client()
        resp = c.post("/api/slack/commands", data=body,
                      content_type="application/x-www-form-urlencoded",
                      HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
                      HTTP_X_SLACK_SIGNATURE=sig)
        assert resp.status_code == 200
        assert SlackRunThread.objects.filter(
            opp_slug="rural-tb", run_id="run-001",
        ).exists()

        # 2. Now simulate the opp.updated broadcast that opp_broadcast
        #    would emit when the run writes its first Drive artifact.
        #    Call dispatch_tick directly (bypassing Channels layer) to
        #    keep the test deterministic.
        thread = SlackRunThread.objects.get(opp_slug="rural-tb", run_id="run-001")
        from apps.slack.dispatcher import dispatch_tick
        dispatch_tick(thread_id=thread.pk)

        # Expect: chat.postMessage for the new phase tile, chat.update for parent.
        assert web_inst.chat_postMessage.call_count >= 1
        assert web_inst.chat_update.call_count >= 1
        # Phase 1 message landed.
        phase_post = next(
            c for c in web_inst.chat_postMessage.call_args_list
            if c.kwargs.get("thread_ts") == "1.1"
        )
        serialized = repr(phase_post.kwargs["blocks"])
        assert "Idea to Design" in serialized
