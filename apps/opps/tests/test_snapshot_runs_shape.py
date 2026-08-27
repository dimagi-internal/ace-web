"""`snapshot.runs` must carry the fields the Runs tab renders.

This is the test that was missing. The Runs tab (#727) reads `snapshot.runs`,
but `serialize_opp_snapshot` hand-wrote a six-field subset — run_id,
current_phase, current_step, mode, last_actor, last_actor_at — so every run
rendered as an empty bar labelled "queued" under a "PHASE 1 -> 1" axis. The
data was computed correctly and dropped one serializer short of the UI.

The component tests passed throughout, because they hand the component a
fixture. Nothing asserted that the ENDPOINT produces that fixture's shape.
That gap is what this file closes.
"""
from __future__ import annotations

import pytest

from apps.opps.serializers import serialize_run_summary
from apps.opps.sync import RunSummary

# Every field the Runs tab actually reads. Adding a column to the tab means
# adding it here first.
RUNS_TAB_FIELDS = {
    "run_id",
    "phase_states",       # the per-phase track
    "phases_done",        # "x/y" and the fallback label
    "phases_total",       # the axis: "PHASE 1 -> N"
    "latest_phase_done",  # "last step completed" when there is no cursor
    "current_phase",      # the live cursor
    "current_step",
    "lifecycle_status",
    "has_error_phase",    # the ⚠ on a run that broke
    "folder_id",          # the Drive deep-link
    "last_actor_at",      # "last activity"
}


def _row(**over) -> RunSummary:
    base = dict(
        run_id="20260813-2126", folder_id="fold-1",
        current_phase=None, current_step=None, mode="default",
        last_actor=None, last_actor_at="2026-08-14T03:26:00Z",
        phases_total=10, phases_done=6, latest_phase_done="qa-and-training",
        phase_states=[
            {"ordinal": 1, "name": "idea-to-design", "status": "done"},
            {"ordinal": 2, "name": "commcare-setup", "status": "error"},
        ],
        has_error_phase=True,
    )
    base.update(over)
    return RunSummary(**base)


@pytest.mark.parametrize("field", sorted(RUNS_TAB_FIELDS))
def test_every_field_the_runs_tab_reads_is_served(field):
    assert field in serialize_run_summary(_row())


def test_the_phase_track_survives_serialisation_intact():
    out = serialize_run_summary(_row())
    assert out["phase_states"] == [
        {"ordinal": 1, "name": "idea-to-design", "status": "done"},
        {"ordinal": 2, "name": "commcare-setup", "status": "error"},
    ]
    # phases_total is what the axis label is built from; 0 rendered "PHASE 1 -> 1".
    assert out["phases_total"] == 10


def test_a_datetime_last_actor_at_is_normalised_to_a_string():
    import datetime

    out = serialize_run_summary(
        _row(last_actor_at=datetime.datetime(2026, 8, 14, 3, 26, tzinfo=datetime.UTC))
    )
    assert out["last_actor_at"] == "2026-08-14T03:26:00Z"


def test_a_stale_cached_row_serialises_rather_than_raising():
    """Snapshot rows come from a Redis cache; one written before a field
    existed has no such attribute. asdict() would raise — see
    snapshot_cache._KEY_VERSION v9, which this serializer must not repeat."""
    from dataclasses import dataclass

    @dataclass
    class _Stale:
        run_id: str = "20260724-0846"
        current_phase: str | None = None
        current_step: str | None = None
        mode: str | None = None
        last_actor: str | None = None
        last_actor_at: str | None = None
        # no phase_states, no has_error_phase, no folder_id

    out = serialize_run_summary(_Stale())
    assert out["run_id"] == "20260724-0846"
