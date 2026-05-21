import pytest

from apps.opps.schemas import (  # noqa: F401 — import-existence smoke test
    ArtifactOut,
    ForkProgress,
    GateOut,
    OppCardOut,
    OppCreateIn,
    OppForkIn,
    OppForkOut,
    OppPatchIn,
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


def test_opp_card_accepts_null_updated_at():
    """Regression for #466.

    Opps with no completed run must serialise ``updated_at`` as null
    rather than the Unix epoch — the frontend OppCard guards on truthy
    ``last_activity_at`` to render "last —" instead of "last 12/31/1969".
    """
    raw = {
        "slug": "cosmetics-fgd-pilot",
        "title": "Cosmetics FGD Pilot",
        "current_phase": None,
        "current_skill": None,
        "run_count": 0,
        "last_run_id": None,
        "updated_at": None,
    }
    parsed = OppCardOut.model_validate(raw)
    assert parsed.updated_at is None
    # And the field can be omitted entirely (defaults to None).
    raw2 = {**raw}
    del raw2["updated_at"]
    parsed2 = OppCardOut.model_validate(raw2)
    assert parsed2.updated_at is None


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


def test_opp_create_in_round_trip():
    obj = OppCreateIn.model_validate({
        "title": "Literacy Onboarding",
        "slug": "lit-onboard-20260514",
        "idea": "Start with a simple idea.",
        "mode": "review",
    })
    assert obj.title == "Literacy Onboarding"
    assert obj.slug == "lit-onboard-20260514"
    assert obj.mode == "review"
    assert obj.pdd == ""


def test_opp_create_in_requires_title():
    with pytest.raises(ValueError):
        OppCreateIn.model_validate({"title": "", "slug": "lit-onboard"})


def test_opp_create_in_requires_slug():
    with pytest.raises(ValueError):
        OppCreateIn.model_validate({"title": "My Opp", "slug": "x"})  # too short


def test_opp_patch_in_round_trip():
    # All fields optional — empty body is valid.
    obj = OppPatchIn.model_validate({})
    assert obj.title is None

    obj2 = OppPatchIn.model_validate({"title": "Updated Title"})
    assert obj2.title == "Updated Title"


def test_opp_patch_in_rejects_empty_title():
    with pytest.raises(ValueError):
        OppPatchIn.model_validate({"title": ""})
