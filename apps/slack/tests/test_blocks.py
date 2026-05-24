from apps.slack.blocks import (
    parent_state_hash,
    phase_state_hash,
    render_parent_card,
    render_phase_tile,
)


def _snapshot_fixture():
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
            "decisions": [],
        },
        "phases": [
            {"name": "idea-to-design", "display_name": "Idea to Design",
             "agent": "idea-to-design", "ordinal": 1},
            {"name": "scenarios-and-acceptance",
             "display_name": "Scenarios & Acceptance",
             "agent": "scenarios-and-acceptance", "ordinal": 2},
        ],
    }


def test_phase_tile_compact_and_clean():
    snap = _snapshot_fixture()
    blocks = render_phase_tile(snap, phase_name="idea-to-design",
                               opp_slug="rural-health", workspace_slug="dimagi-team")
    serialized = repr(blocks)
    assert "Phase 1" in serialized
    assert "Idea to Design" in serialized
    assert "1/1 done" in serialized
    assert "mean 82/100" in serialized
    assert "Open phase" in serialized
    assert "rural-health" in serialized


def test_phase_tile_shows_running_skill():
    snap = _snapshot_fixture()
    blocks = render_phase_tile(snap, phase_name="scenarios-and-acceptance",
                               opp_slug="rural-health", workspace_slug="dimagi-team")
    serialized = repr(blocks)
    assert "Running: scenarios" in serialized


def test_phase_tile_shows_decisions_with_review_button():
    snap = _snapshot_fixture()
    snap["current_run"]["decisions"] = [
        {"id": "d-001", "phase": "idea-to-design", "status": "ai-default"},
        {"id": "d-002", "phase": "idea-to-design", "status": "overridden"},
    ]
    blocks = render_phase_tile(snap, phase_name="idea-to-design",
                               opp_slug="rural-health", workspace_slug="dimagi-team")
    serialized = repr(blocks)
    assert "2 decisions" in serialized
    assert "1 overridden" in serialized
    assert "Review decisions" in serialized


def test_parent_card_clean():
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
    assert "Open in ace-web" in serialized
    # No emojis
    for emoji in ["🟡", "⏸", "↗", "🍴", ":clipboard:", ":x:", ":grey_question:"]:
        assert emoji not in serialized


def test_state_hashes_stable():
    snap = _snapshot_fixture()
    h1 = phase_state_hash(snap, "idea-to-design")
    h2 = phase_state_hash(snap, "idea-to-design")
    assert h1 == h2
    snap["current_run"]["steps"][0]["status"] = "qa-failed"
    h3 = phase_state_hash(snap, "idea-to-design")
    assert h3 != h1
    ph1 = parent_state_hash(snap, elapsed_seconds=300)
    ph2 = parent_state_hash(snap, elapsed_seconds=320)
    assert ph1 == ph2
    ph3 = parent_state_hash(snap, elapsed_seconds=400)
    assert ph3 != ph1
