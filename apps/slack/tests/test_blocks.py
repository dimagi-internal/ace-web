from apps.slack.blocks import (
    parent_state_hash,
    phase_state_hash,
    render_parent_card,
    render_phase_tile,
)


def _snapshot(*, decisions=None, steps=None):
    return {
        "display_name": "Rural Health TB",
        "current_run": {
            "run_id": "20260523-0750",
            "steps": steps or [
                {"phase": "idea-to-design", "skill_name": "draft-pdd",
                 "status": "complete", "ordinal": 0,
                 "judge": {"score_pct": 82}},
                {"phase": "scenarios", "skill_name": "scenarios",
                 "status": "running", "ordinal": 0, "judge": None},
            ],
            "decisions": decisions or [],
        },
        "phases": [
            {"name": "idea-to-design", "display_name": "Idea to Design",
             "agent": "idea-to-design", "ordinal": 1},
            {"name": "scenarios", "display_name": "Scenarios",
             "agent": "scenarios-and-acceptance", "ordinal": 2},
        ],
    }


def _extract_urls(blocks: list[dict]) -> list[str]:
    urls = []
    for b in blocks:
        if b["type"] == "actions":
            for el in b["elements"]:
                if "url" in el:
                    urls.append(el["url"])
    return urls


def _extract_button_labels(blocks: list[dict]) -> list[str]:
    labels = []
    for b in blocks:
        if b["type"] == "actions":
            for el in b["elements"]:
                labels.append(el["text"]["text"])
    return labels


# -- render_phase_tile -------------------------------------------------------


class TestPhaseTile:
    def test_includes_phase_number_and_name(self):
        blocks = render_phase_tile(
            _snapshot(), phase_name="idea-to-design",
            opp_slug="rural-health", workspace_slug="ws")
        text = blocks[0]["text"]["text"]
        assert "Phase 1" in text
        assert "Idea to Design" in text

    def test_includes_progress(self):
        blocks = render_phase_tile(
            _snapshot(), phase_name="idea-to-design",
            opp_slug="rural-health", workspace_slug="ws")
        text = blocks[0]["text"]["text"]
        assert "1/1 done" in text
        assert "mean 82/100" in text

    def test_shows_running_skill(self):
        blocks = render_phase_tile(
            _snapshot(), phase_name="scenarios",
            opp_slug="rural-health", workspace_slug="ws")
        text = blocks[0]["text"]["text"]
        assert "Running: scenarios" in text

    def test_shows_decision_count_and_overrides(self):
        snap = _snapshot(decisions=[
            {"id": "d-1", "phase": "idea-to-design", "status": "ai-default"},
            {"id": "d-2", "phase": "idea-to-design", "status": "overridden"},
            {"id": "d-3", "phase": "idea-to-design", "status": "overridden"},
        ])
        blocks = render_phase_tile(
            snap, phase_name="idea-to-design",
            opp_slug="rural-health", workspace_slug="ws")
        text = blocks[0]["text"]["text"]
        assert "3 decisions" in text
        assert "2 overridden" in text

    def test_review_decisions_button_when_decisions_exist(self):
        snap = _snapshot(decisions=[
            {"id": "d-1", "phase": "idea-to-design", "status": "ai-default"},
        ])
        labels = _extract_button_labels(render_phase_tile(
            snap, phase_name="idea-to-design",
            opp_slug="x", workspace_slug="ws"))
        assert "Review decisions" in labels

    def test_no_review_button_without_decisions(self):
        labels = _extract_button_labels(render_phase_tile(
            _snapshot(), phase_name="idea-to-design",
            opp_slug="x", workspace_slug="ws"))
        assert "Review decisions" not in labels

    def test_urls_include_run_id(self):
        urls = _extract_urls(render_phase_tile(
            _snapshot(), phase_name="idea-to-design",
            opp_slug="rural-health", workspace_slug="ws"))
        for url in urls:
            assert "run_id=20260523-0750" in url, f"Missing run_id in: {url}"

    def test_urls_include_phase(self):
        urls = _extract_urls(render_phase_tile(
            _snapshot(), phase_name="idea-to-design",
            opp_slug="rural-health", workspace_slug="ws"))
        for url in urls:
            assert "phase=idea-to-design" in url, f"Missing phase in: {url}"

    def test_urls_include_view_phase(self):
        urls = _extract_urls(render_phase_tile(
            _snapshot(), phase_name="idea-to-design",
            opp_slug="rural-health", workspace_slug="ws"))
        for url in urls:
            assert "view=phase" in url, f"Missing view=phase in: {url}"

    def test_urls_include_workspace_and_slug(self):
        urls = _extract_urls(render_phase_tile(
            _snapshot(), phase_name="idea-to-design",
            opp_slug="rural-health", workspace_slug="dimagi-team"))
        for url in urls:
            assert "/w/dimagi-team/opps/rural-health" in url

    def test_no_emojis(self):
        snap = _snapshot(decisions=[
            {"id": "d-1", "phase": "idea-to-design", "status": "ai-default"},
        ])
        blocks = render_phase_tile(
            snap, phase_name="idea-to-design",
            opp_slug="test-opp", workspace_slug="ws")
        serialized = repr(blocks)
        for emoji in ["🍴", "📋", "🟡", "⏸", "↗", ":clipboard:",
                      ":x:", ":grey_question:"]:
            assert emoji not in serialized

    def test_qa_failed_shown(self):
        snap = _snapshot(steps=[
            {"phase": "idea-to-design", "skill_name": "draft-pdd",
             "status": "qa-failed", "ordinal": 0, "judge": None},
        ])
        blocks = render_phase_tile(
            snap, phase_name="idea-to-design",
            opp_slug="x", workspace_slug="ws")
        assert "1 failed QA" in blocks[0]["text"]["text"]


# -- render_parent_card ------------------------------------------------------


class TestParentCard:
    def test_includes_display_name_and_run_id(self):
        blocks = render_parent_card(
            _snapshot(), opp_slug="rural-health",
            workspace_slug="ws", triggerer_display="@jj",
            elapsed_seconds=0)
        text = blocks[0]["text"]["text"]
        assert "Rural Health TB" in text
        assert "20260523-0750" in text

    def test_includes_triggerer_and_elapsed(self):
        blocks = render_parent_card(
            _snapshot(), opp_slug="rural-health",
            workspace_slug="ws", triggerer_display="@alice",
            elapsed_seconds=900)
        text = blocks[0]["text"]["text"]
        assert "@alice" in text
        assert "15m elapsed" in text

    def test_shows_active_phase(self):
        blocks = render_parent_card(
            _snapshot(), opp_slug="rural-health",
            workspace_slug="ws", triggerer_display="@jj",
            elapsed_seconds=0)
        text = blocks[0]["text"]["text"]
        assert "Phase 2" in text
        assert "Scenarios" in text

    def test_url_includes_run_id(self):
        urls = _extract_urls(render_parent_card(
            _snapshot(), opp_slug="rural-health",
            workspace_slug="ws", triggerer_display="@jj",
            elapsed_seconds=0))
        assert len(urls) >= 1
        assert "run_id=20260523-0750" in urls[0]

    def test_stop_button_when_thread_id(self):
        labels = _extract_button_labels(render_parent_card(
            _snapshot(), opp_slug="rural-health",
            workspace_slug="ws", triggerer_display="@jj",
            elapsed_seconds=0, thread_id="abc-123"))
        assert "Stop watching" in labels

    def test_no_stop_button_without_thread_id(self):
        labels = _extract_button_labels(render_parent_card(
            _snapshot(), opp_slug="rural-health",
            workspace_slug="ws", triggerer_display="@jj",
            elapsed_seconds=0))
        assert "Stop watching" not in labels

    def test_stopped_display(self):
        blocks = render_parent_card(
            _snapshot(), opp_slug="rural-health",
            workspace_slug="ws", triggerer_display="@jj",
            elapsed_seconds=0, stopped_by_display="@bob",
            thread_id="abc")
        text = blocks[0]["text"]["text"]
        assert "Stopped by @bob" in text
        labels = _extract_button_labels(blocks)
        assert "Stop watching" not in labels

    def test_no_emojis(self):
        blocks = render_parent_card(
            _snapshot(), opp_slug="x", workspace_slug="ws",
            triggerer_display="@jj", elapsed_seconds=0)
        serialized = repr(blocks)
        for emoji in ["🟡", "⏸", "↗"]:
            assert emoji not in serialized


# -- state hashes ------------------------------------------------------------


class TestStateHashes:
    def test_phase_hash_stable(self):
        snap = _snapshot()
        h1 = phase_state_hash(snap, "idea-to-design")
        h2 = phase_state_hash(snap, "idea-to-design")
        assert h1 == h2

    def test_phase_hash_changes_on_status(self):
        snap = _snapshot()
        h1 = phase_state_hash(snap, "idea-to-design")
        snap["current_run"]["steps"][0]["status"] = "qa-failed"
        h2 = phase_state_hash(snap, "idea-to-design")
        assert h1 != h2

    def test_parent_hash_buckets_by_minute(self):
        snap = _snapshot()
        ph1 = parent_state_hash(snap, elapsed_seconds=300)
        ph2 = parent_state_hash(snap, elapsed_seconds=320)
        assert ph1 == ph2
        ph3 = parent_state_hash(snap, elapsed_seconds=400)
        assert ph3 != ph1
