import json

from apps.slack.blocks import render_phase_tile
from apps.slack.blocks_decisions import (
    decisions_state_hash,
    render_decision_message,
    render_decision_summary,
    render_fork_modal,
)


def _decision_fixture(*, decision_id="d-001", phase="idea-to-design",
                       skill="draft-pdd", status="ai-default"):
    return {
        "id": decision_id,
        "phase": phase,
        "phase_raw": phase,
        "skill": skill,
        "question": "Should the Learn app include a supervisor dashboard?",
        "ai_default": "Yes — include a supervisor module with aggregate views",
        "override": "",
        "options_considered": [
            "Yes — include a supervisor module",
            "No — keep it FLW-only for v1",
            "Simplified dashboard only",
        ],
        "source": "pdd",
        "status": status,
        "notes": "",
    }


def _snapshot_with_decisions():
    return {
        "display_name": "Rural Health TB Screening",
        "current_run": {
            "run_id": "run-007",
            "steps": [
                {"phase": "idea-to-design", "skill_name": "draft-pdd",
                 "status": "complete", "ordinal": 0,
                 "judge": {"score_pct": 82}},
            ],
            "decisions": [
                _decision_fixture(decision_id="d-001", status="ai-default"),
                _decision_fixture(decision_id="d-002", status="ai-default",
                                  skill="review-pdd"),
                _decision_fixture(decision_id="d-003", status="overridden"),
            ],
        },
        "phases": [
            {"name": "idea-to-design", "display_name": "Idea to Design",
             "agent": "idea-to-design", "ordinal": 1},
        ],
    }


# -- render_decision_message -------------------------------------------------


class TestRenderDecisionMessage:
    def test_basic_structure(self):
        dec = _decision_fixture()
        blocks = render_decision_message(
            dec, opp_slug="rural-health", phase_name="idea-to-design",
            decision_index=1,
        )
        assert len(blocks) == 4  # context + section + context(voter) + actions
        assert blocks[0]["type"] == "context"
        assert "Decision #1" in blocks[0]["elements"][0]["text"]
        assert blocks[1]["type"] == "section"
        assert "supervisor dashboard" in blocks[1]["text"]["text"]
        assert blocks[2]["type"] == "context"
        assert "No answer yet" in blocks[2]["elements"][0]["text"]
        assert blocks[3]["type"] == "actions"

    def test_with_vote(self):
        dec = _decision_fixture()
        vote = {"answer": "No — keep it FLW-only", "voter_slack_id": "U123",
                "voter_name": "alice"}
        blocks = render_decision_message(
            dec, opp_slug="rural-health", phase_name="idea-to-design",
            vote=vote, decision_index=3,
        )
        voter_block = blocks[2]
        assert "<@U123>" in voter_block["elements"][0]["text"]
        assert "No — keep it FLW-only" in voter_block["elements"][0]["text"]

    def test_option_buttons_capped_at_4_plus_other(self):
        dec = _decision_fixture()
        dec["options_considered"] = ["A", "B", "C", "D", "E", "F"]
        blocks = render_decision_message(
            dec, opp_slug="x", phase_name="p", decision_index=1,
        )
        actions = blocks[3]
        assert len(actions["elements"]) == 5  # 4 options + Other...

    def test_action_values_encode_slug_phase_id(self):
        dec = _decision_fixture(decision_id="d-042")
        blocks = render_decision_message(
            dec, opp_slug="my-opp", phase_name="design",
            decision_index=1,
        )
        first_button = blocks[3]["elements"][0]
        assert first_button["value"].startswith("my-opp:design:d-042:")

    def test_skill_appears_in_eyebrow(self):
        dec = _decision_fixture(skill="review-pdd")
        blocks = render_decision_message(
            dec, opp_slug="x", phase_name="p", decision_index=1,
        )
        assert "review-pdd" in blocks[0]["elements"][0]["text"]


# -- render_decision_summary -------------------------------------------------


class TestRenderDecisionSummary:
    def test_no_decisions(self):
        assert render_decision_summary([], {}) == ""

    def test_no_votes(self):
        decs = [_decision_fixture(decision_id="d-001")]
        summary = render_decision_summary(decs, {})
        assert "1 decision" in summary
        assert "none answered" in summary

    def test_with_votes(self):
        decs = [_decision_fixture(decision_id="d-001"),
                _decision_fixture(decision_id="d-002")]
        votes = {
            "d-001": {"answer": "X", "voter_slack_id": "U1", "voter_name": "a"},
        }
        summary = render_decision_summary(decs, votes)
        assert "2 decisions" in summary
        assert "1 answered" in summary
        assert "1 person" in summary

    def test_multiple_voters(self):
        decs = [_decision_fixture(decision_id="d-001"),
                _decision_fixture(decision_id="d-002")]
        votes = {
            "d-001": {"answer": "X", "voter_slack_id": "U1", "voter_name": "a"},
            "d-002": {"answer": "Y", "voter_slack_id": "U2", "voter_name": "b"},
        }
        summary = render_decision_summary(decs, votes)
        assert "2 answered" in summary
        assert "2 people" in summary


# -- decisions_state_hash ---------------------------------------------------


class TestDecisionsStateHash:
    def test_stable(self):
        decs = [_decision_fixture()]
        h1 = decisions_state_hash(decs, {})
        h2 = decisions_state_hash(decs, {})
        assert h1 == h2

    def test_changes_with_vote(self):
        decs = [_decision_fixture(decision_id="d-001")]
        h1 = decisions_state_hash(decs, {})
        h2 = decisions_state_hash(decs, {"d-001": {"answer": "X"}})
        assert h1 != h2


# -- render_fork_modal -------------------------------------------------------


class TestRenderForkModal:
    def test_modal_structure(self):
        votes = {
            "d-001": {"answer": "Option B", "voter_name": "alice"},
            "d-002": {"answer": "Custom", "voter_name": "bob"},
        }
        modal = render_fork_modal("my-opp", "idea-to-design", votes, "run-007")
        assert modal["type"] == "modal"
        assert modal["callback_id"] == "ace_fork_with_answers"
        metadata = json.loads(modal["private_metadata"])
        assert metadata["opp_slug"] == "my-opp"
        assert metadata["phase_name"] == "idea-to-design"
        # Mode picker defaults to keep-overrides-only
        mode_block = modal["blocks"][2]
        assert mode_block["element"]["initial_option"]["value"] == "keep-overrides-only"


# -- render_phase_tile with votes -------------------------------------------


class TestPhaseTileWithVotes:
    def test_no_votes_shows_old_fork_button(self):
        snap = _snapshot_with_decisions()
        blocks = render_phase_tile(
            snap, phase_name="idea-to-design",
            opp_slug="rural-health", workspace_slug="dimagi-team",
        )
        serialized = repr(blocks)
        assert "Fork from here" in serialized
        assert "Fork & re-run with answers" not in serialized

    def test_with_votes_shows_fork_with_answers(self):
        snap = _snapshot_with_decisions()
        votes = {"d-001": {"answer": "X", "voter_slack_id": "U1", "voter_name": "a"}}
        blocks = render_phase_tile(
            snap, phase_name="idea-to-design",
            opp_slug="rural-health", workspace_slug="dimagi-team",
            votes=votes,
        )
        serialized = repr(blocks)
        assert "Fork & re-run with answers" in serialized
        assert "Fork from here" not in serialized

    def test_decision_summary_appears(self):
        snap = _snapshot_with_decisions()
        votes = {"d-001": {"answer": "X", "voter_slack_id": "U1", "voter_name": "a"}}
        blocks = render_phase_tile(
            snap, phase_name="idea-to-design",
            opp_slug="rural-health", workspace_slug="dimagi-team",
            votes=votes,
        )
        serialized = repr(blocks)
        assert "3 decisions" in serialized
        assert "1 answered" in serialized
