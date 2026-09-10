"""A skill fork trims ``products`` at DOTTED depth by the plugin's attribution (ace#2354).

Before this the forker had a top-level-key attributed path and nothing to
feed it: the plugin declared no product-key → skill map, so every skill fork
carried the fork phase's ``products`` whole and UNATTRIBUTED. On the
canonical case — a Phase 7 fork at ``demo-narrative`` — that seeded the new
run with a stale ``synthetic.narrative`` and stale ``synthetic.ddd_*`` beside
the kept ``synthetic.source`` / ``.workflows`` / ``.labs_opp_id``.

The plugin now ships ``phases.<phase>.productProducers`` in
``docs/phase-products-schema.json`` with DOTTED keys and a trailing-``*``
prefix wildcard; ``skills.product_producers`` reads it. This file pins what
the forker does with it:

* a key whose producer ran BELOW the fork skill carries; one whose producer
  IS the fork skill, a later skill, or the phase agent itself (its write-back
  lands after every skill) drops;
* the trim walks INTO a block when the map attributes its children
  (``synthetic`` has no entry of its own; its children do);
* a key the map does not cover — or whose declared producer the registry
  cannot place — is CARRIED and named in the note, never dropped silently;
* the carried block is no longer marked UNATTRIBUTED.

Fixture note: the committed stub registry has no Phase 7, so these tests
build a plugin dir from the stub plus a frontmatter-only
``synthetic-data-and-workflows`` agent (``demo-data-setup`` →
``demo-narrative``) and the JSON the real dump script emits.
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
from django.test import override_settings

from apps.opps.opp_forker import _skill_fork_phase_block
from apps.opps.skills import reset_cache, resolve_fork_point

STUB_PLUGIN = Path("apps/opps/tests/fixtures/stub_plugin").resolve()

PHASE7_AGENT = """---
name: synthetic-data-and-workflows
description: Phase 7 stub — frontmatter only.
model: inherit
phase: synthetic-data-and-workflows
phase_display: Synthetic Data
phase_ordinal: 7
skills:
  - { name: demo-data-setup, has_judge: false }
  - { name: demo-narrative,  has_judge: true }
---
"""

PHASE7_PRODUCERS = {
    "synthetic.provider": "demo-data-setup",
    "synthetic.labs_opp_id": "demo-data-setup",
    "synthetic.workflows": "demo-data-setup",
    "synthetic.source": "demo-data-setup",
    "synthetic.render_code_patched_this_run": "demo-data-setup",
    "synthetic.narrative": "demo-narrative",
    "synthetic.walkthroughs": "synthetic-data-and-workflows",
    "synthetic.promoted_template": "synthetic-data-and-workflows",
    "synthetic.ddd_*": "synthetic-data-and-workflows",
}

# Shaped after spark-facilitator/20260909-1211's real Phase-7 block.
SOURCE_PHASE7 = {
    "status": "done",
    "verdict": "pass",
    "completed_at": "2026-09-09T14:02:00+00:00",
    "steps": {
        "demo-data-setup": {"status": "done", "artifact": "7-synthetic/demo-data-setup.md"},
        "demo-data-setup-qa": {"status": "done"},
        "demo-narrative": {"status": "done", "artifact": "7-synthetic/demo-narrative.md"},
    },
    "products": {
        "synthetic": {
            "provider": "ace-run",
            "labs_opp_id": 10042,
            "workflows": {"program_admin": {"workflow_id": 91, "run_url": "https://labs/x"}},
            "source": {"provider": "ace-run", "record_counts": {"user_visits": 276}},
            "render_code_patched_this_run": True,
            "narrative": {"why_brief_ref": "7-synthetic/why_brief.yaml", "validated": True},
            "walkthroughs": [{"web_view_link": "https://canopy/ddd/x/1", "eval_score": 4.2}],
            "promoted_template": {"workflow_id": 91, "scope": "program:7"},
            "ddd_terminal_status": "converged_clean",
            "ddd_open_strategy_findings": 0,
        },
    },
}


def _write_schema_json(plugin: Path, phases: dict) -> None:
    doc = {
        "_generated": "test fixture shaped like scripts/dump-phase-products-schema.ts output",
        "productProducersSemantics": "exact, nearest ancestor, trailing * prefix",
        "phases": {
            name: {
                "schema": {},
                "requiredProductKeys": [],
                "productProducers": producers,
                "unattributedProductKeys": [],
            }
            for name, producers in phases.items()
        },
    }
    (plugin / "docs").mkdir(parents=True, exist_ok=True)
    (plugin / "docs" / "phase-products-schema.json").write_text(json.dumps(doc))


@pytest.fixture
def plugin(tmp_path):
    """The stub registry + a Phase 7 agent + the plugin's attribution JSON."""
    plugin = tmp_path / "plugin"
    shutil.copytree(STUB_PLUGIN, plugin)
    (plugin / "agents" / "synthetic-data-and-workflows.md").write_text(PHASE7_AGENT)
    _write_schema_json(
        plugin,
        {
            "synthetic-data-and-workflows": PHASE7_PRODUCERS,
            # A kept parent with a deeper override, on the stub's commcare phase.
            "commcare-setup": {"apps": "pdd-to-learn-app", "apps.deliver": "app-deploy"},
        },
    )
    with override_settings(ACE_PLUGIN_PATH=str(plugin)):
        reset_cache()
        yield plugin
    reset_cache()


def _fork(source, *, skill):
    point = resolve_fork_point(skill=skill)
    return _skill_fork_phase_block(
        point,
        copy.deepcopy(source) if source is not None else None,
        source_run_id="20260909-1211",
        source_state_read=True,
    )


# ── the canonical case: Phase 7 fork at demo-narrative ──────────────────


def test_a_phase7_fork_at_demo_narrative_carries_only_what_demo_data_setup_wrote(plugin):
    block, carried = _fork(SOURCE_PHASE7, skill="demo-narrative")
    src = SOURCE_PHASE7["products"]["synthetic"]
    assert block["products"] == {
        "synthetic": {
            "provider": src["provider"],
            "labs_opp_id": src["labs_opp_id"],
            "workflows": src["workflows"],
            "source": src["source"],
            "render_code_patched_this_run": src["render_code_patched_this_run"],
        }
    }
    assert carried.products_attributed is True
    assert sorted(carried.products_keys_carried) == [
        "synthetic.labs_opp_id",
        "synthetic.provider",
        "synthetic.render_code_patched_this_run",
        "synthetic.source",
        "synthetic.workflows",
    ]
    assert sorted(carried.products_keys_dropped) == [
        "synthetic.ddd_open_strategy_findings",
        "synthetic.ddd_terminal_status",
        "synthetic.narrative",
        "synthetic.promoted_template",
        "synthetic.walkthroughs",
    ]


def test_the_carried_block_is_no_longer_marked_unattributed(plugin):
    block, carried = _fork(SOURCE_PHASE7, skill="demo-narrative")
    assert "UNATTRIBUTED" not in block["fork_note"]
    assert "by attribution" in block["fork_note"]
    assert "synthetic.narrative" in block["fork_note"]
    assert "synthetic.ddd_terminal_status" in block["fork_note"]
    assert block["fork_note"] == carried.note


def test_the_phase_agent_own_keys_drop_at_any_fork_point_in_the_phase(plugin):
    # walkthroughs / promoted_template / ddd_* are written in the agent's
    # write-back AFTER every skill, so no skill fork inside the phase predates
    # them — even one at the last skill.
    _, carried = _fork(SOURCE_PHASE7, skill="demo-narrative")
    agent_keys = (
        "synthetic.walkthroughs",
        "synthetic.promoted_template",
        "synthetic.ddd_terminal_status",
    )
    for key in agent_keys:
        assert key in carried.products_keys_dropped, key


def test_a_fork_at_the_first_skill_drops_the_whole_block(plugin):
    block, carried = _fork(SOURCE_PHASE7, skill="demo-data-setup")
    assert "products" not in block
    assert block["status"] == "pending"
    assert carried.products_keys_carried == ()
    assert "synthetic.source" in carried.products_keys_dropped
    assert "synthetic.narrative" in carried.products_keys_dropped


def test_keys_the_map_does_not_cover_are_carried_and_named(plugin):
    source = copy.deepcopy(SOURCE_PHASE7)
    source["products"]["synthetic"]["extra_handle"] = {"x": 1}
    source["products"]["mystery"] = {"y": 2}
    block, carried = _fork(source, skill="demo-narrative")
    assert block["products"]["synthetic"]["extra_handle"] == {"x": 1}
    assert block["products"]["mystery"] == {"y": 2}
    assert "synthetic.extra_handle" in carried.products_keys_carried
    assert "mystery" in carried.products_keys_carried
    assert "synthetic.extra_handle" in block["fork_note"]
    assert "mystery" in block["fork_note"]
    assert "unmapped" in block["fork_note"]


def test_a_declared_producer_the_registry_cannot_place_is_carried_not_dropped(plugin, monkeypatch):
    # A producer name that is not a registry skill and not this phase's agent:
    # the plugin says who wrote it but ace-web cannot order it against the
    # fork skill, so the safe direction is carry + name (dropping could lose
    # a handoff a downstream phase reads; carrying costs an overwrite).
    producers = dict(PHASE7_PRODUCERS)
    producers["synthetic.source"] = "skill-ace-web-has-never-heard-of"
    monkeypatch.setattr("apps.opps.skills.product_producers", lambda phase: producers)
    block, carried = _fork(SOURCE_PHASE7, skill="demo-narrative")
    src = SOURCE_PHASE7["products"]["synthetic"]["source"]
    assert block["products"]["synthetic"]["source"] == src
    assert "synthetic.source" in carried.products_keys_carried
    assert "synthetic.source" not in carried.products_keys_dropped
    assert "synthetic.source" in block["fork_note"]


def test_a_wildcard_matches_a_ddd_key_the_fixture_never_named(plugin):
    source = copy.deepcopy(SOURCE_PHASE7)
    source["products"]["synthetic"]["ddd_run_id"] = "r-7"
    _, carried = _fork(source, skill="demo-narrative")
    assert "synthetic.ddd_run_id" in carried.products_keys_dropped


# ── a kept parent with a deeper override (stub commcare phase) ───────────


def test_a_deeper_entry_trims_inside_a_carried_parent(plugin):
    source = {
        "status": "done",
        "steps": {"pdd-to-learn-app": {"status": "done"}, "app-deploy": {"status": "done"}},
        "products": {
            "apps": {
                "learn": {"nova_app_id": "abc", "hq_app_id": "h1"},
                "deliver": {"nova_app_id": "def", "hq_app_id": "h2"},
                "domain": "connect-ace-prod",
            }
        },
    }
    block, carried = _fork(source, skill="app-deploy")
    # `apps` → pdd-to-learn-app (below the fork) carries; `apps.deliver` →
    # app-deploy (the fork skill) drops out of the carried parent.
    assert block["products"] == {
        "apps": {"learn": {"nova_app_id": "abc", "hq_app_id": "h1"}, "domain": "connect-ace-prod"}
    }
    assert carried.products_keys_carried == ("apps",)
    assert carried.products_keys_dropped == ("apps.deliver",)
    assert carried.products_attributed is True


def test_a_dropped_parent_takes_its_subtree_with_it(plugin):
    source = {
        "status": "done",
        "steps": {"pdd-to-learn-app": {"status": "done"}, "app-deploy": {"status": "done"}},
        "products": {"apps": {"learn": {"hq_app_id": "h1"}, "deliver": {"hq_app_id": "h2"}}},
    }
    block, carried = _fork(source, skill="pdd-to-deliver-app")
    # Fork BELOW... no: pdd-to-deliver-app sits between pdd-to-learn-app and
    # app-deploy, so `apps` (learn-app) still predates it and carries, while
    # `apps.deliver` (app-deploy) is later and drops.
    assert block["products"] == {"apps": {"learn": {"hq_app_id": "h1"}}}
    assert carried.products_keys_dropped == ("apps.deliver",)


def test_the_top_level_only_attributed_path_still_works_unchanged(plugin, monkeypatch):
    # The shape ace-web#765 already tested: a flat map on the stub phase.
    monkeypatch.setattr(
        "apps.opps.skills.product_producers",
        lambda phase: {"apps": "pdd-to-learn-app", "deployment": "app-deploy"},
    )
    source = {
        "status": "done",
        "steps": {"pdd-to-learn-app": {"status": "done"}},
        "products": {
            "apps": {"learn": {}},
            "deployment": {"released_at": "x"},
            "unmapped": {"x": 1},
        },
    }
    block, carried = _fork(source, skill="app-deploy")
    assert block["products"] == {"apps": {"learn": {}}, "unmapped": {"x": 1}}
    assert sorted(carried.products_keys_carried) == ["apps", "unmapped"]
    assert carried.products_keys_dropped == ("deployment",)
    assert "UNATTRIBUTED" not in block["fork_note"]
