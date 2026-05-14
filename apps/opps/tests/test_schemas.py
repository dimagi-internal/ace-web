import pytest

from apps.opps.schemas import (  # noqa: F401 — import-existence smoke test
    ArtifactOut,
    ForkProgress,
    GateOut,
    OppCardOut,
    OppForkIn,
    OppForkOut,
    OppRunOut,
    OppSnapshotOut,
    ScorecardOut,
    StepSnapshotOut,
    VerdictOut,
)


def test_opp_card_round_trip():
    raw = {
        "slug": "lit-onboard-20260514",
        "title": "Literacy Onboarding",
        "current_phase": "scenarios-and-acceptance",
        "current_skill": "scenarios-and-acceptance",
        "run_count": 3,
        "last_run_id": "run-003",
        "updated_at": "2026-05-13T09:00:00Z",
    }
    parsed = OppCardOut.model_validate(raw)
    assert parsed.run_count == 3


def test_fork_in_validation():
    with pytest.raises(ValueError):
        OppForkIn(fork_at_phase="")
    obj = OppForkIn(fork_at_phase="ocs-setup", source_run_id="run-002")
    assert obj.source_run_id == "run-002"


def test_fork_progress_status_union():
    for status in ["unknown", "counting", "copying", "finalizing", "done", "error"]:
        ForkProgress.model_validate({"status": status, "progress": 0.0})


def test_verdict_and_gate_minimum_fields():
    VerdictOut.model_validate(
        {
            "skill": "ocs-setup",
            "phase": "ocs-setup",
            "kind": "quick",
            "score": 87,
            "verdict": "pass",
            "rationale": "Smoke tests passed.",
            "decided_at": "2026-05-12T10:00:00Z",
        }
    )
    GateOut.model_validate(
        {
            "skill": "ocs-setup",
            "decision": "approved",
            "decided_by": "alice@example.com",
            "decided_at": "2026-05-12T10:00:00Z",
            "note": None,
        }
    )
