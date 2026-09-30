"""Replay: when each product appears, and what each skill took in / handed on."""
from __future__ import annotations

from apps.opps import replay


def _step(skill, phase, ordinal, status="complete"):
    return {
        "skill_name": skill, "display_name": skill, "phase": phase, "phase_display": phase,
        "ordinal": ordinal, "status": status, "started_at": None, "completed_at": None,
        "error": None, "judge": None, "qa_result": None, "artifacts": [],
    }


def _snapshot(products):
    return {
        "slug": "opp",
        "current_run": {
            "run_id": "r1",
            "steps": [
                _step("idea-to-pdd", "idea-to-design", 1),
                _step("idea-to-pdd-eval", "idea-to-design", 2),
                _step("pdd-to-learn-app", "commcare-setup", 3),
                _step("app-deploy", "commcare-setup", 4),
                _step("ocs-agent-setup", "ocs-setup", 5, status="pending"),
            ],
            "products": products,
        },
    }


def _seq(events, kind, skill):
    return next(e["seq"] for e in events if e["kind"] == kind and e.get("skill") == skill)


def test_product_appears_at_its_producers_step_end():
    snap = _snapshot([{"id": "a", "phase": "commcare-setup", "producer": "pdd-to-learn-app"}])
    events = replay.build_timeline(snap)["events"]
    [item] = replay.build_products(snap, events)
    assert item["reveal_seq"] == _seq(events, "step_end", "pdd-to-learn-app")


def test_unattributed_product_appears_when_its_phase_finishes():
    snap = _snapshot([{"id": "p", "phase": "idea-to-design", "producer": None}])
    events = replay.build_timeline(snap)["events"]
    [item] = replay.build_products(snap, events)
    assert item["reveal_seq"] == _seq(events, "step_end", "idea-to-pdd-eval")


def test_producer_outside_the_run_falls_back_to_the_phase():
    snap = _snapshot([{"id": "a", "phase": "commcare-setup", "producer": "not-in-run"}])
    events = replay.build_timeline(snap)["events"]
    [item] = replay.build_products(snap, events)
    assert item["reveal_seq"] == _seq(events, "step_end", "app-deploy")


def test_product_whose_phase_recorded_no_steps_has_no_beat():
    snap = _snapshot([{"id": "c", "phase": "ocs-setup", "producer": None}])
    events = replay.build_timeline(snap)["events"]
    assert replay.build_products(snap, events)[0]["reveal_seq"] is None


def test_timeline_act_carries_products_and_flow(monkeypatch):
    monkeypatch.setattr(replay, "_manifest_artifacts", lambda: [])
    snap = _snapshot([{"id": "a", "phase": "commcare-setup", "producer": "pdd-to-learn-app"}])
    data = replay.build_replay_payload(snap)["acts"][0]["data"]
    assert data["products"][0]["reveal_seq"] is not None
    assert set(data["flow"]) == {
        "idea-to-pdd", "idea-to-pdd-eval", "pdd-to-learn-app", "app-deploy", "ocs-agent-setup",
    }


MANIFEST = [
    {"path": "inputs/", "produced_by": "external",
     "consumed_by": ["ace-orchestrator", "idea-to-pdd"], "phase": "design",
     "description": "Human-curated evidence pack. Any combination of docs."},
    {"path": "1-design/idea-to-pdd.md", "produced_by": "idea-to-pdd",
     "consumed_by": ["ace-orchestrator", "idea-to-pdd-eval", "pdd-to-learn-app", "idea-to-pdd"],
     "phase": "design", "description": "The PDD."},
    {"path": "3-commcare-setup/learn-app.md", "produced_by": "pdd-to-learn-app",
     "consumed_by": ["app-deploy"], "phase": "commcare-setup", "description": ""},
]


def _ladder():
    return replay.build_ladder(_snapshot([]))


def test_flow_inputs_name_their_producer_and_its_phase():
    flow = replay.build_flow(_ladder(), MANIFEST)
    learn_inputs = flow["pdd-to-learn-app"]["inputs"]
    assert [(i["path"], i["producer"], i["producer_phase"]) for i in learn_inputs] == [
        ("1-design/idea-to-pdd.md", "idea-to-pdd", "idea-to-design"),
    ]
    external = flow["idea-to-pdd"]["inputs"]
    assert external[0]["producer"] == "external"
    assert external[0]["description"] == "Human-curated evidence pack."


def test_flow_outputs_list_downstream_skills_without_the_orchestrator_or_self():
    flow = replay.build_flow(_ladder(), MANIFEST)
    [pdd] = flow["idea-to-pdd"]["outputs"]
    assert [c["skill"] for c in pdd["consumers"]] == ["idea-to-pdd-eval", "pdd-to-learn-app"]
    assert pdd["consumers"][1]["phase"] == "commcare-setup"
    # A skill never lists its own output as an input.
    assert all(i["path"] != "1-design/idea-to-pdd.md" for i in flow["idea-to-pdd"]["inputs"])


def test_flow_is_empty_not_an_error_without_a_manifest():
    flow = replay.build_flow(_ladder(), [])
    assert flow["idea-to-pdd"] == {"inputs": [], "outputs": []}


# --------------------------------------------------------------------------- #
# previews — shown at the beat that CAPTURED them
# --------------------------------------------------------------------------- #
def _with_capturer():
    snap = _snapshot([])
    snap["current_run"]["steps"].insert(4, _step("app-screenshot-capture", "qa-and-training", 5))
    return snap


def test_preview_appears_when_its_capturer_finishes_not_with_the_app():
    """The Learn app is built in Phase 3 but photographed in Phase 6; its
    screenshots live with Phase 3, and must still wait for Phase 6."""
    snap = _with_capturer()
    snap["current_run"]["products"] = [{
        "id": "learn", "phase": "commcare-setup", "producer": "pdd-to-learn-app",
        "previews": [{"file_id": "f1", "captured_by": "app-screenshot-capture"}],
    }]
    events = replay.build_timeline(snap)["events"]
    [item] = replay.build_products(snap, events)
    assert item["reveal_seq"] == _seq(events, "step_end", "pdd-to-learn-app")
    assert item["previews"][0]["reveal_seq"] == _seq(events, "step_end", "app-screenshot-capture")


def test_preview_without_a_capturer_rides_with_its_product():
    snap = _snapshot([{
        "id": "learn", "phase": "commcare-setup", "producer": "pdd-to-learn-app",
        "previews": [{"file_id": "f1", "captured_by": None}],
    }])
    events = replay.build_timeline(snap)["events"]
    [item] = replay.build_products(snap, events)
    assert item["previews"][0]["reveal_seq"] == item["reveal_seq"]


def test_preview_is_never_shown_before_its_product():
    snap = _snapshot([{
        "id": "learn", "phase": "commcare-setup", "producer": "app-deploy",
        "previews": [{"file_id": "f1", "captured_by": "idea-to-pdd"}],
    }])
    events = replay.build_timeline(snap)["events"]
    [item] = replay.build_products(snap, events)
    assert item["previews"][0]["reveal_seq"] == item["reveal_seq"]


def test_preview_whose_capturer_has_not_run_waits_for_the_end():
    """A fork carries Phase 3's previews before its Phase 6 has run again."""
    snap = _snapshot([{
        "id": "learn", "phase": "commcare-setup", "producer": "pdd-to-learn-app",
        "previews": [{"file_id": "f1", "captured_by": "app-screenshot-capture"}],
    }])
    events = replay.build_timeline(snap)["events"]
    [item] = replay.build_products(snap, events)
    assert item["previews"][0]["reveal_seq"] is None


def test_preview_from_a_utility_capturer_appears_when_its_phase_ends():
    """``output-preview-capture`` is called at a phase's end with no step of
    its own; its frames land at that phase's last step_end."""
    snap = _snapshot([{
        "id": "opp", "phase": "idea-to-design", "producer": "idea-to-pdd",
        "previews": [{"file_id": "f1", "captured_by": "output-preview-capture",
                      "captured_phase": "commcare-setup"}],
    }])
    events = replay.build_timeline(snap)["events"]
    [item] = replay.build_products(snap, events)
    assert item["previews"][0]["reveal_seq"] == _seq(events, "step_end", "app-deploy")
