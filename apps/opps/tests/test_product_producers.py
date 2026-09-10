"""``product_producers(phase)`` reads the plugin's product-key attribution (ace#2354).

The ACE plugin now declares which skill writes each ``phases.<phase>.products``
key — ``PRODUCT_PRODUCERS`` in ``lib/phase-products-schema.ts``, emitted as
``phases.<phase>.productProducers`` in ``docs/phase-products-schema.json`` so
ace-web can read it without a TypeScript toolchain. Keys are DOTTED paths
relative to ``products`` (``synthetic.source``); values are skill names (or the
phase agent's name for keys the agent writes in its own write-back); a trailing
``*`` on the last segment is a key-segment prefix (``synthetic.ddd_*``).

Contract this file pins:

* the map for a phase comes back as declared, dotted keys intact;
* ``None`` — not ``{}`` — when the plugin has no attribution for the phase
  (``null`` in the JSON, a phase the JSON does not list, or a plugin old enough
  to have no JSON at all), so the forker's carry-all fallback still works;
* the resolver mirrors the plugin's documented semantics: exact match, nearest
  attributed ancestor, trailing-wildcard prefix, exact-over-wildcard.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from django.test import override_settings

from apps.opps.skills import product_producers, reset_cache, resolve_product_producer

STUB_PLUGIN = Path("apps/opps/tests/fixtures/stub_plugin").resolve()

PHASE7 = {
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


def _write_schema_json(plugin_dir: Path, phases: dict) -> None:
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
    (plugin_dir / "docs").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "docs" / "phase-products-schema.json").write_text(json.dumps(doc))


@pytest.fixture
def plugin_with_producers(tmp_path):
    plugin = tmp_path / "plugin"
    shutil.copytree(STUB_PLUGIN, plugin)
    _write_schema_json(
        plugin,
        {
            "synthetic-data-and-workflows": PHASE7,
            "commcare-setup": {"apps": "app-deploy"},
            "scenarios-and-acceptance": None,
        },
    )
    with override_settings(ACE_PLUGIN_PATH=str(plugin)):
        reset_cache()
        yield plugin
    reset_cache()


def test_returns_the_declared_dotted_map_for_a_phase(plugin_with_producers):
    assert product_producers("synthetic-data-and-workflows") == PHASE7
    assert product_producers("commcare-setup") == {"apps": "app-deploy"}


def test_returns_a_copy_so_a_caller_cannot_poison_the_cache(plugin_with_producers):
    first = product_producers("commcare-setup")
    assert first is not None
    first["apps"] = "someone-else"
    assert product_producers("commcare-setup") == {"apps": "app-deploy"}


def test_none_when_the_json_says_null_or_omits_the_phase(plugin_with_producers):
    # `null` is the plugin's spelling of "declares none for this phase".
    assert product_producers("scenarios-and-acceptance") is None
    assert product_producers("phase-the-plugin-never-heard-of") is None


def test_none_on_a_plugin_too_old_to_ship_the_json():
    # The committed stub has no docs/phase-products-schema.json — exactly the
    # shape of a plugin predating ace#2354. The forker must keep its carry-all
    # fallback, so this is None, never {} and never an exception.
    with override_settings(ACE_PLUGIN_PATH=str(STUB_PLUGIN)):
        reset_cache()
        try:
            assert product_producers("commcare-setup") is None
        finally:
            reset_cache()


def test_none_when_the_json_is_malformed(tmp_path):
    plugin = tmp_path / "plugin"
    shutil.copytree(STUB_PLUGIN, plugin)
    (plugin / "docs").mkdir()
    (plugin / "docs" / "phase-products-schema.json").write_text("{not json")
    with override_settings(ACE_PLUGIN_PATH=str(plugin)):
        reset_cache()
        try:
            assert product_producers("commcare-setup") is None
        finally:
            reset_cache()


def test_reset_cache_reloads_from_the_new_plugin_path(plugin_with_producers, tmp_path):
    assert product_producers("commcare-setup") == {"apps": "app-deploy"}
    other = tmp_path / "other"
    shutil.copytree(STUB_PLUGIN, other)
    _write_schema_json(other, {"commcare-setup": {"apps": "pdd-to-learn-app"}})
    with override_settings(ACE_PLUGIN_PATH=str(other)):
        # Without reset the per-process cache still answers for the old path.
        assert product_producers("commcare-setup") == {"apps": "app-deploy"}
        reset_cache()
        assert product_producers("commcare-setup") == {"apps": "pdd-to-learn-app"}
    reset_cache()


# ── resolver semantics (mirrors lib/phase-products-schema.ts::productProducer) ──


def test_exact_match():
    assert resolve_product_producer(PHASE7, "synthetic.narrative") == "demo-narrative"


def test_a_deeper_path_inherits_its_nearest_attributed_ancestor():
    assert resolve_product_producer(PHASE7, "synthetic.source.record_counts") == "demo-data-setup"
    assert (
        resolve_product_producer({"connect": "connect-opp-setup"}, "connect.opportunity.url")
        == "connect-opp-setup"
    )


def test_a_deeper_entry_overrides_a_shallower_one_for_its_subtree():
    m = {"solicitation": "solicitation-create", "solicitation.awarded": "solicitation-review"}
    assert resolve_product_producer(m, "solicitation.url") == "solicitation-create"
    assert resolve_product_producer(m, "solicitation.awarded") == "solicitation-review"
    assert resolve_product_producer(m, "solicitation.awarded.org_slug") == "solicitation-review"


def test_trailing_wildcard_is_a_prefix_on_one_segment_only():
    agent = "synthetic-data-and-workflows"
    assert resolve_product_producer(PHASE7, "synthetic.ddd_terminal_status") == agent
    assert resolve_product_producer(PHASE7, "synthetic.ddd_open_strategy_findings") == agent
    assert resolve_product_producer(PHASE7, "synthetic.ddd_run_id.nested") == agent
    assert resolve_product_producer(PHASE7, "synthetic.dddx") is None
    assert resolve_product_producer(PHASE7, "synthetic") is None
    assert resolve_product_producer(PHASE7, "") is None


def test_an_exact_entry_outranks_a_wildcard_at_the_same_depth():
    m = {"synthetic.ddd_*": "agent", "synthetic.ddd_special": "demo-narrative"}
    assert resolve_product_producer(m, "synthetic.ddd_special") == "demo-narrative"
    assert resolve_product_producer(m, "synthetic.ddd_other") == "agent"
