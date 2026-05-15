from apps.slack.blocks import (
    render_parent_card, render_phase_tile, render_progress_bar,
    phase_state_hash, parent_state_hash,
)


def _snapshot_fixture():
    """Minimal OppSnapshot-shaped dict. Real OppSnapshot is a Pydantic
    model; for renderer tests we use dicts to avoid Pydantic coupling."""
    return {
        "display_name": "Rural Health TB Screening",
        "current_run": {
            "run_id": "run-007",
            "steps": [
                {"phase": "idea-to-design", "skill_name": "draft-pdd",
                 "status": "complete", "ordinal": 0,
                 "judge": {"score_pct": 82}},
                {"phase": "scenarios-and-acceptance", "skill_name": "scenarios",
                 "status": "running", "ordinal": 0, "judge": None},
            ],
        },
        "phases": [
            {"name": "idea-to-design", "display_name": "Idea to Design",
             "agent": "idea-to-design", "ordinal": 1},
            {"name": "scenarios-and-acceptance",
             "display_name": "Scenarios & Acceptance",
             "agent": "scenarios-and-acceptance", "ordinal": 2},
        ],
    }


def test_progress_bar_renders_blocks():
    assert render_progress_bar(0, 4) == "░░░░░░░░░░ 0%"
    assert render_progress_bar(2, 4) == "▓▓▓▓▓░░░░░ 50%"
    assert render_progress_bar(4, 4) == "▓▓▓▓▓▓▓▓▓▓ 100%"
    # Total of 0 means "no skills yet" — render empty bar.
    assert render_progress_bar(0, 0) == "░░░░░░░░░░ 0%"


def test_phase_tile_for_complete_phase():
    snap = _snapshot_fixture()
    blocks = render_phase_tile(snap, phase_name="idea-to-design",
                               opp_slug="rural-health", workspace_slug="dimagi-team")
    serialized = repr(blocks)
    assert "Phase 1" in serialized
    assert "Idea to Design" in serialized
    assert "1/1 done" in serialized
    assert "mean 82" in serialized
    assert "Fork from here" in serialized
    assert "rural-health" in serialized   # deep-link present


def test_phase_tile_for_running_phase_shows_current_skill():
    snap = _snapshot_fixture()
    blocks = render_phase_tile(snap, phase_name="scenarios-and-acceptance",
                               opp_slug="rural-health", workspace_slug="dimagi-team")
    serialized = repr(blocks)
    assert "Currently: scenarios" in serialized
    # Fork button is disabled until at least one skill is complete in this phase.
    assert "Fork from here" not in serialized


def test_parent_card_includes_run_id_and_active_phase():
    snap = _snapshot_fixture()
    blocks = render_parent_card(snap, opp_slug="rural-health",
                                workspace_slug="dimagi-team",
                                triggerer_display="@jjackson",
                                elapsed_seconds=900)
    serialized = repr(blocks)
    assert "Rural Health TB Screening" in serialized
    assert "run-007" in serialized
    assert "@jjackson" in serialized
    assert "Phase 2" in serialized
    assert "Scenarios & Acceptance" in serialized


def test_state_hashes_stable_and_change_meaningfully():
    snap = _snapshot_fixture()
    h1 = phase_state_hash(snap, "idea-to-design")
    h2 = phase_state_hash(snap, "idea-to-design")
    assert h1 == h2
    # Mutating the snapshot changes the hash.
    snap["current_run"]["steps"][0]["status"] = "qa-failed"
    h3 = phase_state_hash(snap, "idea-to-design")
    assert h3 != h1
    # Parent card uses elapsed bucketed to minutes — two calls 30s apart
    # in the same minute bucket should match.
    ph1 = parent_state_hash(snap, elapsed_seconds=300)
    ph2 = parent_state_hash(snap, elapsed_seconds=320)
    assert ph1 == ph2
    ph3 = parent_state_hash(snap, elapsed_seconds=400)
    assert ph3 != ph1
