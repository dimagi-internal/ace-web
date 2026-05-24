from apps.slack.blocks_decisions import (
    decisions_state_hash,
    render_decision_summary,
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
