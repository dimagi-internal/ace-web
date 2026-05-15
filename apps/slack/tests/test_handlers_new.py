from unittest.mock import MagicMock, patch

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
    link = SlackUserLink.objects.create(
        installation=inst, slack_user_id="U_JJ", ace_user=jj,
        slack_email="jj@dimagi.com", slack_real_name="JJ",
    )
    return inst, link, jj


@pytest.mark.django_db
def test_new_opens_modal(setup):
    inst, link, _ = setup
    with patch("apps.slack.verbs_new._get_client") as get_client:
        client = MagicMock()
        get_client.return_value = client
        from apps.slack.verbs_new import handle_new
        resp = handle_new(installation=inst, user_link=link,
                          channel_id="C1", trigger_id="tg1")
    assert resp == {}
    client.open_view.assert_called_once()
    view = client.open_view.call_args.kwargs["view"]
    assert view["type"] == "modal"
    serialized = repr(view)
    assert "Name" in serialized
    assert "Idea" in serialized


@pytest.mark.django_db
def test_new_modal_submission_starts_run(setup):
    inst, link, _ = setup
    with patch("apps.slack.verbs_new.start_run_from_slack") as start, \
         patch("apps.slack.verbs_new._get_client") as get_client:
        start.return_value = ("rural-tb", "run-001")
        client = MagicMock()
        get_client.return_value = client
        client.post_message.return_value = "1.1"
        from apps.slack.verbs_new import handle_new_submission
        payload = {
            "type": "view_submission",
            "team": {"id": "T1"},
            "user": {"id": "U_JJ"},
            "view": {
                "callback_id": "ace_new_modal",
                "private_metadata": '{"channel_id": "C1"}',
                "state": {"values": {
                    "name_block": {"name_input": {"value": "Rural TB"}},
                    "idea_block": {"idea_input": {"value": "Screen TB in rural clinics"}},
                }},
            },
        }
        resp = handle_new_submission(payload)
    assert resp.get("response_action") in (None, "clear")
    start.assert_called_once()
    kwargs = start.call_args.kwargs
    assert "Screen TB" in kwargs["slug_or_link"] or kwargs.get("idea_text")
