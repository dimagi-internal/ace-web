"""Tests that the serializers produce the exact JSON shape the frontend expects."""
import pytest

from apps.opps.serializers import (
    serialize_opp_card,
    serialize_opp_snapshot,
    serialize_step_snapshot,
)
from apps.opps.sync import load_opp
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)


@pytest.fixture
def snap():
    client = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    ace_id = client.folder_id("ACE")
    return load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")


def test_serialize_opp_snapshot_top_level_keys(snap):
    data = serialize_opp_snapshot(snap)
    assert set(data.keys()) == {
        "opp", "pdd_body", "current_run", "phases", "runs", "selected_run_id",
    }
    # phases is a list (possibly empty if ACE_PLUGIN_PATH isn't a real plugin dir).
    assert isinstance(data["phases"], list)
    # Flat layout has no multi-run structure; runs[] is empty.
    assert data["runs"] == []
    # selected_run_id matches the synthesised single-run id.
    assert data["selected_run_id"] == "r1"


def test_serialize_opp_card_fields(snap):
    card = serialize_opp_card(snap.opp, snap.current_run)
    assert card["slug"] == "malaria-pilot"
    assert card["display_name"] == "Malaria Pilot — Northern Mozambique"
    # Flat layout synthesizes a single run with id "r1".
    assert card["current_run_id"] == "r1"
    assert card["current_step"] == "app-test"
    assert "labels" in card


def test_serialize_opp_snapshot_current_run_has_all_steps(snap):
    data = serialize_opp_snapshot(snap)
    steps = data["current_run"]["steps"]
    skills = [s["skill_name"] for s in steps]
    # All canonical skills are emitted as rows (with status pending if no
    # artifacts are present on Drive). Count comes from plugin agent
    # frontmatter — at least 19 today.
    assert "idea-to-pdd" in skills
    assert "app-deploy" in skills
    assert len(skills) >= 19


def test_serialize_step_snapshot_no_judge_no_gates(snap):
    """When no verdicts/ files and no state.yaml gates: are present, the
    step payload contains null judge and empty gates for frontend compat."""
    step_snap = next(
        s for s in snap.current_run.steps if s.step.skill_name == "idea-to-pdd"
    )
    data = serialize_step_snapshot(step_snap)
    assert data["judge"] is None
    assert data["gates"] == []


def test_serialize_step_snapshot_artifacts(snap):
    """idea-to-pdd's artifact is the opp-root pdd.md."""
    step_snap = next(
        s for s in snap.current_run.steps if s.step.skill_name == "idea-to-pdd"
    )
    data = serialize_step_snapshot(step_snap)
    assert len(data["artifacts"]) == 1
    assert data["artifacts"][0]["name"] == "pdd.md"
    assert "drive_web_link" in data["artifacts"][0]


# --- Regression tests for the score normalization + display_name surface --

def test_normalize_score_pct_handles_both_scales():
    from apps.opps.serializers import normalize_score_pct
    assert normalize_score_pct(None) is None
    # 0-10 scale → multiplied to 0-100
    assert normalize_score_pct(8.5) == 85.0
    assert normalize_score_pct(0) == 0
    # 0-100 scale → passed through
    assert normalize_score_pct(82) == 82.0
    assert normalize_score_pct(100) == 100.0
    # Edge: exactly 10 is ambiguous — heuristic treats it as 0-10 ⇒ 100/100
    assert normalize_score_pct(10) == 100.0


def test_serialize_judge_emits_score_pct_and_passes_object_criteria_through():
    """Server emits both raw score and a 0-100 score_pct. Object-shaped
    criteria values (the plugin's ``dimensions`` shape with ``score`` /
    ``weight``) must flow through unchanged so the frontend can render
    both the legacy number form and the structured object form."""
    from apps.opps.parsers import JudgeVerdict
    from apps.opps.serializers import serialize_judge
    j = JudgeVerdict(
        score=8.5,
        passed=True,
        evaluated_at="2026-05-03T00:00:00Z",
        criteria={
            "correctness": 9,                                  # legacy bare number
            "tone": {"score": 8, "weight": 0.3, "weakness": "occasionally curt"},
        },
        rationale="Solid output.",
    )
    out = serialize_judge(j)
    assert out is not None
    assert out["score"] == 8.5
    assert out["score_pct"] == 85.0
    # Object-shaped criterion is passed through verbatim — frontend
    # JudgeVerdict.tsx's extractScore picks the numeric out.
    assert out["criteria"]["correctness"] == 9
    assert out["criteria"]["tone"]["score"] == 8
    assert out["criteria"]["tone"]["weakness"] == "occasionally curt"


def test_serialize_step_snapshot_includes_display_name(snap):
    """display_name resolves from the plugin's SKILL.md H1 (e.g. ``# Idea to PDD``).
    Falls back to the slug when the plugin has no display metadata."""
    step_snap = next(
        s for s in snap.current_run.steps if s.step.skill_name == "idea-to-pdd"
    )
    data = serialize_step_snapshot(step_snap)
    # Either the real plugin H1 or the kebab-titlecased fallback.
    assert data["display_name"], "every step must have a non-empty display_name"
    assert "idea" in data["display_name"].lower()
