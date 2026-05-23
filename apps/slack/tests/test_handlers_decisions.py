"""Tests for decision voting + fork interaction handlers."""
import json
from unittest.mock import MagicMock, patch

import pytest

from apps.slack.verbs_decisions import (
    handle_answer_decision,
    handle_answer_other_open,
    handle_answer_other_submission,
    handle_fork_with_answers,
)


@pytest.fixture
def mock_thread():
    thread = MagicMock()
    thread.pk = "thread-uuid"
    thread.opp_slug = "rural-health"
    thread.run_id = "run-007"
    thread.channel_id = "C123"
    thread.parent_ts = "1234.5678"
    thread.phase_messages = {
        "idea-to-design": {
            "ts": "1235.0",
            "last_state_hash": "abc",
            "votes": {},
            "decision_messages": {},
        },
    }
    thread.installation = MagicMock()
    thread.installation.ace_workspace = MagicMock()
    thread.installation.ace_workspace.slug = "dimagi-team"
    thread.broken_at = None
    thread.stopped_at = None

    def save_side_effect(update_fields=None):
        pass
    thread.save = MagicMock(side_effect=save_side_effect)
    return thread


def _action_payload(*, action_id, value, team_id="T1", user_id="U1",
                    channel_id="C123", message_ts="1236.0",
                    trigger_id="trig-1"):
    return {
        "type": "block_actions",
        "team": {"id": team_id},
        "user": {"id": user_id, "username": "alice"},
        "channel": {"id": channel_id},
        "message": {"ts": message_ts},
        "trigger_id": trigger_id,
        "actions": [{"action_id": action_id, "value": value}],
    }


def _snapshot_with_decisions():
    return {
        "display_name": "Rural Health",
        "current_run": {
            "run_id": "run-007",
            "steps": [
                {"phase": "idea-to-design", "skill_name": "draft-pdd",
                 "status": "complete", "ordinal": 0, "judge": None},
            ],
            "decisions": [
                {"id": "d-001", "phase": "idea-to-design", "skill": "draft-pdd",
                 "question": "Include supervisor?", "default": "Yes",
                 "options_considered": ["Yes", "No"], "source": "pdd",
                 "status": "open", "notes": ""},
            ],
        },
        "phases": [
            {"name": "idea-to-design", "display_name": "Idea to Design",
             "agent": "idea-to-design", "ordinal": 1},
        ],
    }


class TestHandleAnswerDecision:
    @patch("apps.slack.verbs_decisions._update_phase_tile_summary")
    @patch("apps.slack.verbs_decisions._update_decision_message_after_vote")
    @patch("apps.slack.verbs_decisions._find_active_thread")
    def test_records_vote(self, mock_find, mock_update_dec, mock_update_tile, mock_thread):
        mock_find.return_value = mock_thread
        payload = _action_payload(
            action_id="answer_decision:d-001:abc",
            value="rural-health:idea-to-design:d-001:No",
        )
        action = payload["actions"][0]
        result = handle_answer_decision(payload, action)
        assert result == {}
        # Vote was recorded
        votes = mock_thread.phase_messages["idea-to-design"]["votes"]
        assert "d-001" in votes
        assert votes["d-001"]["answer"] == "No"
        assert votes["d-001"]["voter_slack_id"] == "U1"
        mock_thread.save.assert_called()

    @patch("apps.slack.verbs_decisions._find_active_thread")
    def test_no_thread_returns_error(self, mock_find):
        mock_find.return_value = None
        payload = _action_payload(
            action_id="answer_decision:d-001:abc",
            value="rural-health:idea-to-design:d-001:No",
        )
        action = payload["actions"][0]
        result = handle_answer_decision(payload, action)
        assert "No active tracking" in result.get("text", "")

    def test_malformed_value(self):
        payload = _action_payload(action_id="answer_decision:x", value="bad")
        action = payload["actions"][0]
        result = handle_answer_decision(payload, action)
        assert "malformed" in result.get("text", "")


class TestHandleAnswerOtherOpen:
    @patch("apps.slack.verbs_decisions.client_for")
    @patch("apps.slack.handlers._get_installation")
    def test_opens_modal(self, mock_install, mock_client_for):
        mock_install.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client_for.return_value = mock_client

        payload = _action_payload(
            action_id="answer_decision_other:d-001",
            value="rural-health:idea-to-design:d-001",
        )
        action = payload["actions"][0]
        result = handle_answer_other_open(payload, action)
        assert result == {}
        mock_client.open_view.assert_called_once()
        view_arg = mock_client.open_view.call_args[1]["view"]
        assert view_arg["callback_id"] == "ace_answer_other"


class TestHandleAnswerOtherSubmission:
    @patch("apps.slack.verbs_decisions._update_phase_tile_summary")
    @patch("apps.slack.verbs_decisions._update_decision_message_after_vote")
    @patch("apps.slack.verbs_decisions._find_active_thread")
    def test_records_custom_answer(self, mock_find, mock_update_dec, mock_update_tile, mock_thread):
        mock_find.return_value = mock_thread
        payload = {
            "type": "view_submission",
            "user": {"id": "U1", "username": "alice"},
            "view": {
                "callback_id": "ace_answer_other",
                "private_metadata": json.dumps({
                    "opp_slug": "rural-health",
                    "phase_name": "idea-to-design",
                    "decision_id": "d-001",
                    "message_ts": "1236.0",
                    "channel_id": "C123",
                }),
                "state": {"values": {
                    "custom_answer": {
                        "custom_answer_input": {"value": "My custom answer"},
                    },
                }},
            },
        }
        result = handle_answer_other_submission(payload)
        assert result == {}
        votes = mock_thread.phase_messages["idea-to-design"]["votes"]
        assert votes["d-001"]["answer"] == "My custom answer"

    @patch("apps.slack.verbs_decisions._find_active_thread")
    def test_empty_answer_returns_error(self, mock_find):
        mock_find.return_value = MagicMock()
        payload = {
            "type": "view_submission",
            "user": {"id": "U1", "username": "alice"},
            "view": {
                "callback_id": "ace_answer_other",
                "private_metadata": json.dumps({
                    "opp_slug": "x", "phase_name": "p",
                    "decision_id": "d", "message_ts": "t", "channel_id": "c",
                }),
                "state": {"values": {
                    "custom_answer": {
                        "custom_answer_input": {"value": "  "},
                    },
                }},
            },
        }
        result = handle_answer_other_submission(payload)
        assert result.get("response_action") == "errors"


class TestHandleForkWithAnswers:
    @patch("apps.slack.verbs_decisions.client_for")
    @patch("apps.slack.handlers._get_installation")
    @patch("apps.slack.verbs_decisions._find_active_thread")
    def test_opens_fork_modal(self, mock_find, mock_install, mock_client_for, mock_thread):
        mock_thread.phase_messages = {
            "idea-to-design": {
                "ts": "1235.0",
                "votes": {"d-001": {"answer": "No", "voter_slack_id": "U1",
                                    "voter_name": "alice"}},
            },
        }
        mock_find.return_value = mock_thread
        mock_install.return_value = mock_thread.installation
        mock_client = MagicMock()
        mock_client_for.return_value = mock_client

        payload = _action_payload(
            action_id="fork_with_answers",
            value="rural-health:idea-to-design:run-007",
        )
        action = payload["actions"][0]
        result = handle_fork_with_answers(payload, action)
        assert result == {}
        mock_client.open_view.assert_called_once()
        view_arg = mock_client.open_view.call_args[1]["view"]
        assert view_arg["callback_id"] == "ace_fork_with_answers"

    @patch("apps.slack.handlers._get_installation")
    @patch("apps.slack.verbs_decisions._find_active_thread")
    def test_no_votes_returns_error(self, mock_find, mock_install, mock_thread):
        mock_thread.phase_messages = {
            "idea-to-design": {"ts": "1235.0", "votes": {}},
        }
        mock_find.return_value = mock_thread
        mock_install.return_value = mock_thread.installation

        payload = _action_payload(
            action_id="fork_with_answers",
            value="rural-health:idea-to-design:run-007",
        )
        action = payload["actions"][0]
        result = handle_fork_with_answers(payload, action)
        assert "No decisions" in result.get("text", "")
