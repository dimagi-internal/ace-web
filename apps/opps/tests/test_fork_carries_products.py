"""A fork must carry each copied phase's typed handoff (ace#1888).

The forker synthesizes a fresh `run_state.yaml` rather than copying one, which
is right for statuses and timestamps and was wrong for exactly one key.

`phases.<phase>.products.*` is the handoff between phases — the Connect
opportunity id, the released Deliver app id, the OCS chatbot, the labs
synthetic opp. A phase downstream of the fork reads it to find the LIVE objects
the copied artifacts describe.

Without it a fork is a convincing shell: every pre-fork phase reads `done`,
every artifact is present, `fork/status` reports `done` with
`files_copied == files_total` — and the first phase that actually runs cannot
find the opportunity all those artifacts are about. Measured on
`spark-facilitator/20260908-2136`, a Phase 7 fork whose six copied phases all
carried `products: None`.
"""
import datetime as dt
from unittest.mock import MagicMock

import pytest
import yaml
from django.test import override_settings

from apps.opps.opp_forker import _build_run_state_yaml, _source_phase_products
from apps.opps.skills import reset_cache

STUB_PLUGIN = "apps/opps/tests/fixtures/stub_plugin"


@pytest.fixture(autouse=True)
def _stub_registry():
    with override_settings(ACE_PLUGIN_PATH=STUB_PLUGIN):
        reset_cache()
        yield
    reset_cache()


# Shaped after spark-facilitator/20260907-1120's real blocks.
SOURCE_PRODUCTS = {
    "design-review": {"pdd": {"doc_id": "1abc"}},
    "commcare-setup": {
        "commcare": {
            "deliver_app": {"id": "61eedcad279046d499d0f05f9ce3dc83"},
        }
    },
}


def _state(fork_ordinal: int, **kw) -> dict:
    return yaml.safe_load(
        _build_run_state_yaml(
            opp_slug="spark-facilitator",
            run_id="20260908-2136",
            owner_email="dev@example.com",
            fork_at_phase="connect-setup",
            fork_ordinal=fork_ordinal,
            forked_from_run_id="20260907-1120",
            now_utc=dt.datetime(2026, 9, 8, 21, 36, tzinfo=dt.UTC),
            **kw,
        )
    )


def test_a_copied_phase_carries_its_products():
    state = _state(3, source_products=SOURCE_PRODUCTS)
    commcare = state["phases"]["commcare-setup"]

    assert commcare["status"] == "done"
    assert commcare["products"]["commcare"]["deliver_app"]["id"] == (
        "61eedcad279046d499d0f05f9ce3dc83"
    )


def test_a_phase_that_will_re_run_does_not_inherit_products():
    # `connect` is the fork point: it re-runs and must mint its own handoff, or
    # it would point at objects the re-run is replacing.
    state = _state(3, source_products={**SOURCE_PRODUCTS, "connect-setup": {"x": 1}})

    assert state["phases"]["connect-setup"]["status"] == "pending"
    assert "products" not in state["phases"]["connect-setup"]


def test_products_travel_verbatim_and_are_not_flattened():
    state = _state(3, source_products=SOURCE_PRODUCTS)
    assert state["phases"]["commcare-setup"]["products"] == SOURCE_PRODUCTS["commcare-setup"]


def test_a_phase_the_source_had_no_products_for_gets_no_empty_key():
    # An empty `products: {}` reads to a downstream phase as "the handoff ran
    # and produced nothing", which is a different claim from "absent".
    state = _state(3, source_products={"commcare-setup": {}})
    assert "products" not in state["phases"]["commcare-setup"]


def test_a_fork_with_no_source_products_is_unchanged():
    # The pre-ace#1888 behaviour, preserved: no products anywhere, no crash.
    state = _state(3)
    for block in state["phases"].values():
        assert "products" not in block


def test_the_rest_of_the_phase_block_is_still_synthesized_not_copied():
    # Only `products` is carried. A source verdict or completed_at would
    # misrepresent the fork as having run these phases itself.
    state = _state(3, source_products=SOURCE_PRODUCTS)
    commcare = state["phases"]["commcare-setup"]
    assert commcare["verdict"] == "seeded"
    assert commcare["completed_at"] == "2026-09-08T21:36:00+00:00"
    assert "steps" in commcare


# ── reading them off the source run ────────────────────────────────


def _drive_with_run_state(body: str) -> MagicMock:
    drive = MagicMock()
    rs = MagicMock()
    rs.id, rs.name, rs.mime_type = "rs", "run_state.yaml", "text/yaml"
    drive.list_files.side_effect = lambda fid: [rs]
    drive.get_content.side_effect = lambda fid, mime: MagicMock(content=body)
    return drive


def test_reads_products_off_the_source_run_state():
    body = yaml.safe_dump(
        {
            "phases": {
                "commcare": {"status": "done", "products": {"a": 1}},
                "connect": {"status": "done"},
            }
        }
    )
    assert _source_phase_products(_drive_with_run_state(body), "run-src") == {
        "commcare": {"a": 1}
    }


@pytest.mark.parametrize(
    "body",
    [
        "",                          # empty file
        "not: [a, mapping",          # malformed yaml
        "phases: null",              # no phases
        "phases: [1, 2]",            # phases is not a map
        "phases: {p: 'a string'}",   # a phase block is not a map
        "phases: {p: {products: 7}}",  # products is not a map
    ],
)
def test_a_source_run_state_it_cannot_read_still_forks(body):
    # Best-effort by design. Failing the whole fork over an unreadable source
    # run_state would be a regression against today's behaviour, which reads
    # it not at all.
    assert _source_phase_products(_drive_with_run_state(body), "run-src") == {}


def test_a_source_run_with_no_run_state_still_forks():
    drive = MagicMock()
    drive.list_files.side_effect = lambda fid: []
    assert _source_phase_products(drive, "run-src") == {}


def test_a_drive_error_is_swallowed_not_raised():
    drive = MagicMock()
    drive.list_files.side_effect = RuntimeError("drive is down")
    assert _source_phase_products(drive, "run-src") == {}
