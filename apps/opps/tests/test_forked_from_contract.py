"""``forked_from`` must be a STRING in a synthesized run_state.yaml.

Regression test for the artifact pane going dead on any opp with a forked
run. ``_build_run_state_yaml`` used to write ``forked_from`` as a dict block
(``{run_id, phase, forked_at}``) on the reasoning that "the plugin doesn't
read this field but humans will". The framework-reader migration made
``canopy_agent_runs`` a reader of it, and its read model declares
``RunSummary.forked_from: str | None`` — the store even documents the
contract: "written as a top-level STRING (the source run id) so the read
model's ``Run.forked_from: str | None`` validates".

A dict therefore raises pydantic ValidationError inside
``store.list_runs`` → every uncached ``load_opp`` 500s → artifact download
(and, once the snapshot cache expires, the whole workbench) breaks for
that opp. Observed in prod on ``spark-facilitator``.
"""
import datetime as dt

import yaml

from apps.opps.opp_forker import _build_run_state_yaml

NOW = dt.datetime(2026, 8, 14, 12, 0, tzinfo=dt.UTC)


def _synth(**overrides) -> dict:
    kwargs = dict(
        opp_slug="spark-facilitator",
        run_id="20260814-1200",
        owner_email="ace@dimagi-ai.com",
        fork_at_phase="idea-to-design",
        fork_ordinal=1,
        forked_from_run_id="20260724-1622",
        now_utc=NOW,
    )
    kwargs.update(overrides)
    return yaml.safe_load(_build_run_state_yaml(**kwargs))


def test_forked_from_is_the_source_run_id_string():
    assert _synth()["forked_from"] == "20260724-1622"


def test_forked_from_validates_against_the_framework_read_model():
    """The exact assertion that was failing in prod: pydantic must accept it."""
    from canopy_agent_runs.schemas import RunSummary

    summary = RunSummary(
        id="20260814-1200",
        agent_slug="ace",
        forked_from=_synth()["forked_from"],
    )
    assert summary.forked_from == "20260724-1622"


def test_seeded_run_also_writes_a_string():
    state = _synth(run_phases=[1, 2])
    assert state["forked_from"] == "20260724-1622"
    assert state["seeded_from"] == "20260724-1622"
