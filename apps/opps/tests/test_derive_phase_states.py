"""`phase_states` — per-phase status in authored order.

`phases_done` is a COUNT. It cannot express a run that cleared phases 1-5,
errored in 6, and then completed 7 — which is a real shape in the record
(hh-poverty-targeting/20260730-2210). The cross-run strip draws one segment
per phase off `phase_states`, so these tests pin the shapes the plugin
actually emits rather than the tidy one.
"""
from __future__ import annotations

from apps.opps.sync import _derive_phase_progress


def _states(state: dict) -> list[tuple[int, str, str]]:
    out = _derive_phase_progress(state, None)["phase_states"]
    return [(p["ordinal"], p["name"], p["status"]) for p in out]


def test_keeps_authored_order_and_ordinals():
    got = _states({"phases": {
        "idea-to-design": {"status": "done"},
        "scenarios-and-acceptance": {"status": "done"},
        "commcare-setup": {"status": "pending"},
    }})
    assert got == [
        (1, "idea-to-design", "done"),
        (2, "scenarios-and-acceptance", "done"),
        (3, "commcare-setup", "pending"),
    ]


def test_preserves_non_terminal_statuses_verbatim():
    """`error`, `blocked` and `skipped` are the whole point of the strip —
    collapsing them to done/pending would erase the signal."""
    got = _states({"phases": {
        "a": {"status": "done"},
        "b": {"status": "error"},
        "c": {"status": "skipped"},
        "d": {"status": "blocked"},
        "e": {"status": "in_progress"},
    }})
    assert [s for _, _, s in got] == [
        "done", "error", "skipped", "blocked", "in_progress",
    ]


def test_an_errored_run_no_longer_claims_to_be_complete():
    """An errored phase used to be indistinguishable from a clean run.

    `_PENDING_STATUSES` is {"pending", "", None}, so an `error` phase counts
    as NON-pending and lands in `phases_done`. A run that errored in phase 3
    of 4 therefore reported 4/4 done AND `lifecycle_status: complete` — the
    badge said "complete" on a run that broke.

    The counts are deliberately unchanged (other callers read `phases_done`
    as "how many phases got through", and reclassifying would flip
    completed-looking historical runs). What changed: a run carrying a broken
    phase may no longer CLAIM completion, and `has_error_phase` +
    `phase_states` say exactly what happened and where.
    """
    prog = _derive_phase_progress({"phases": {
        "p1": {"status": "done"},
        "p2": {"status": "done"},
        "p3": {"status": "error"},
        "p4": {"status": "done"},
    }}, None)
    assert prog["phases_done"] == 4          # count semantics unchanged
    assert prog["status"] != "complete"      # ...but the claim is gone
    assert prog["has_error_phase"] is True
    assert prog["phase_states"][2] == {"ordinal": 3, "name": "p3", "status": "error"}


def test_a_clean_run_still_reads_complete():
    prog = _derive_phase_progress({"phases": {
        "p1": {"status": "done"},
        "p2": {"status": "complete"},
    }}, None)
    assert prog["status"] == "complete"
    assert prog["has_error_phase"] is False


def test_error_status_variants_are_recognised():
    """The plugin emits variants, not a fixed set — `fail-avd-contended`,
    `blocked-on-stale-mcp`. A prefix match catches them; a whitelist did not."""
    for bad in ("error", "blocked", "failed", "fail-avd-contended", "blocked-on-stale-mcp"):
        prog = _derive_phase_progress({"phases": {"p1": {"status": bad}}}, None)
        assert prog["has_error_phase"] is True, bad
        assert prog["status"] != "complete", bad


def test_a_skipped_phase_is_not_an_error():
    """`skipped` and `skipped-by-design` are deliberate, not broken."""
    prog = _derive_phase_progress({"phases": {
        "p1": {"status": "done"},
        "p2": {"status": "skipped"},
        "p3": {"status": "skipped-by-design"},
    }}, None)
    assert prog["has_error_phase"] is False
    assert prog["status"] == "complete"


def test_bare_step_map_phase_shape_b():
    """Older plugin shape: step-name -> status directly under the phase,
    no `status:` and no `steps:` wrapper."""
    got = _states({"phases": {
        "idea-to-design": {"idea-to-pdd": "done", "pdd-to-work-order": "done"},
        "commcare-setup": {"pdd-to-learn-app": "pending"},
    }})
    assert got == [
        (1, "idea-to-design", "done"),
        (2, "commcare-setup", "pending"),
    ]


def test_partially_worked_phase_reads_in_progress_not_pending():
    """A phase with some steps done and some not is mid-flight — the strip
    should show it amber, not empty."""
    got = _states({"phases": {
        "commcare-setup": {"steps": {
            "pdd-to-learn-app": {"status": "done"},
            "app-release": {"status": "pending"},
        }},
    }})
    assert got == [(1, "commcare-setup", "in_progress")]


def test_untouched_phase_reads_pending():
    got = _states({"phases": {
        "closeout": {"steps": {"opp-closeout": {"status": "pending"}}},
    }})
    assert got == [(1, "closeout", "pending")]


def test_non_dict_phase_entry_is_pending_not_a_crash():
    got = _states({"phases": {"weird": "just-a-string"}})
    assert got == [(1, "weird", "pending")]


def test_missing_phases_map_yields_empty_list():
    assert _derive_phase_progress({}, None)["phase_states"] == []
