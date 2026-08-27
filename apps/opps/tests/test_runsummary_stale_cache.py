"""A RunSummary from a stale cache entry must not 500 the page.

Adding `phase_states` + `has_error_phase` to the dataclass (#727, #731) put
objects in Redis that deserialise into the NEW class without those attributes.
`asdict()` raises AttributeError on those, which took `GET /opps` to a hard
500 in production for every workspace with a warm cache.

The cache version (`snapshot_cache._KEY_VERSION`) is the correctness fix — it
retires the old entries. This is the AVAILABILITY fix: a future missed bump
should degrade one card, never the whole list.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.opps import snapshot_cache
from apps.opps.api import _serialize_card_runs_summary, list_opp_runs_for_workspace  # noqa: F401


@dataclass
class _StaleRunSummary:
    """A RunSummary as it existed BEFORE phase_states/has_error_phase — what a
    v8 cache entry unpickles into once the class has moved on."""
    run_id: str = "20260813-2126"
    folder_id: str = "f1"
    current_phase: str | None = None
    current_step: str | None = None
    mode: str | None = "default"
    last_actor: str | None = None
    last_actor_at: str | None = "2026-08-14T03:26:00Z"
    lifecycle_status: str | None = "complete"
    phases_total: int = 4
    phases_done: int = 4
    latest_phase_done: str | None = "closeout"
    # NOTE: no phase_states, no has_error_phase — that is the whole point.


def test_a_stale_runsummary_serialises_instead_of_raising():
    out = _serialize_card_runs_summary(
        [_StaleRunSummary()], phase_meta={}, skill_phase_index={},
    )
    assert len(out) == 1
    assert out[0]["run_id"] == "20260813-2126"


def test_the_card_payload_still_drops_what_it_should():
    out = _serialize_card_runs_summary(
        [_StaleRunSummary()], phase_meta={}, skill_phase_index={},
    )
    # folder_id and phase_states are deliberately not served on the list page
    # (#512 keeps it one call; the card draws only a P{n} chip).
    assert "folder_id" not in out[0]
    assert "phase_states" not in out[0]


def test_a_current_runsummary_serialises_with_the_new_fields():
    from apps.opps.sync import RunSummary

    r = RunSummary(
        run_id="20260819-1435", folder_id="f", current_phase=None, current_step=None,
        mode="default", last_actor=None, last_actor_at=None,
        phase_states=[{"ordinal": 1, "name": "idea-to-design", "status": "done"}],
        has_error_phase=True,
    )
    out = _serialize_card_runs_summary([r], phase_meta={}, skill_phase_index={})
    assert out[0]["has_error_phase"] is True
    assert "phase_states" not in out[0]  # still dropped on the card path


def test_cache_key_version_was_bumped_past_the_dataclass_change():
    """Guards the discipline, not the value: adding a field to a cached
    dataclass REQUIRES retiring old entries."""
    assert snapshot_cache._KEY_VERSION >= "v9"
