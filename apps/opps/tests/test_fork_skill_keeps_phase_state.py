"""A skill fork keeps the fork phase's EARLIER state, not just its files (ace#2341).

A skill-level fork (``fork_at_skill``) copies the fork phase's earlier
artifacts — trimmed by ``producedBy`` ordinal — and then, until this fix,
synthesized that phase's ``run_state`` block as if nothing had happened:
``status: pending``, every step ``pending``, ``products: {}``. The kept work
was orphaned: files present, state unaware. Measured on
``spark-facilitator/20260909-1211 → 20260909-2242`` and reproduced on
``→ 20260910-0541``. The re-run then redid the kept step, orphaned the live
labs workflows named in ``products.synthetic.workflows``, and silently
disabled three QA gates that read ``products.synthetic.*``.

The rule that already trims ARTIFACTS on a skill fork now applies to the
phase's STATE: ``steps.<skill>`` entries from skills of lower ordinal carry
verbatim; the fork skill and later reset to ``pending``; ``products`` carry
by attribution where the plugin declares one and whole-with-a-note where it
does not; the phase reads ``in_progress`` with no ``verdict`` /
``completed_at`` / ``summary_artifact`` so it must re-complete.

Fixture note: phase/skill names come from the stub plugin registry
(``apps/opps/tests/fixtures/stub_plugin/``). In that registry the
``commcare-setup`` phase runs ``pdd-to-learn-app`` → ``pdd-to-deliver-app`` →
``app-deploy`` → ``app-test`` → ``training-materials``.
"""
import copy
import datetime as dt
from unittest.mock import MagicMock

import pytest
import yaml
from django.test import override_settings

from apps.opps.opp_forker import (
    ForkCarried,
    _build_run_state_yaml,
    _skill_fork_phase_block,
    _source_phase_blocks,
    fork_opp,
)
from apps.opps.skills import reset_cache, resolve_fork_point

STUB_PLUGIN = "apps/opps/tests/fixtures/stub_plugin"
NOW = dt.datetime(2026, 9, 10, 5, 41, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def _stub_registry():
    with override_settings(ACE_PLUGIN_PATH=STUB_PLUGIN):
        reset_cache()
        yield
    reset_cache()


# Shaped after spark-facilitator/20260909-1211's real Phase-7 block, on the
# stub's commcare phase. ``pdd-to-learn-app-eval`` / ``app-deploy-qa`` are the
# plugin's documented ``<producer>-eval`` / ``<producer>-qa`` companions
# (skills/README.md § QA vs Eval); ``mystery-step`` is a name the registry
# cannot place at all.
SOURCE_PHASE = {
    "status": "done",
    "verdict": "pass",
    "started_at": "2026-09-09T12:11:00+00:00",
    "completed_at": "2026-09-09T14:02:00+00:00",
    "summary_artifact": "1summary",
    "steps": {
        "pdd-to-learn-app": {
            "status": "done",
            "artifact": "2-commcare/learn-app-summary.md",
            "file_id": "1learn",
            "note": "built on Nova app abc",
        },
        "pdd-to-deliver-app": {"status": "done", "file_id": "1deliver"},
        "pdd-to-learn-app-eval": {"status": "done", "verdict": "pass", "score": 8.5},
        "app-deploy": {"status": "done", "artifact": "2-commcare/deployment-summary.md"},
        "app-deploy-qa": {"status": "done"},
        "app-test": {"status": "done"},
        "training-materials": {"status": "done"},
        "mystery-step": {"status": "done"},
    },
    "products": {
        "apps": {
            "learn": {"nova_app_id": "abc", "hq_app_id": "h1"},
            "deliver": {"nova_app_id": "def", "hq_app_id": "h2"},
        },
        "deployment": {"released_at": "2026-09-09T13:50:00+00:00"},
    },
}


def _fork_block(source=SOURCE_PHASE, *, skill="app-deploy", read=True):
    point = resolve_fork_point(skill=skill)
    return _skill_fork_phase_block(
        point,
        copy.deepcopy(source) if source is not None else None,
        source_run_id="20260909-1211",
        source_state_read=read,
    )


# ── (a) a skill fork carries earlier steps + products, resets the rest ──


def test_steps_before_the_fork_skill_carry_verbatim():
    block, carried = _fork_block()
    steps = block["steps"]
    assert steps["pdd-to-learn-app"] == SOURCE_PHASE["steps"]["pdd-to-learn-app"]
    assert steps["pdd-to-deliver-app"] == SOURCE_PHASE["steps"]["pdd-to-deliver-app"]
    assert "pdd-to-learn-app" in carried.steps_carried
    assert "pdd-to-deliver-app" in carried.steps_carried


def test_the_fork_skill_and_every_later_step_reset_to_pending():
    block, carried = _fork_block()
    steps = block["steps"]
    for name in ("app-deploy", "app-test", "training-materials"):
        assert steps[name] == {"status": "pending"}, name
        assert name in carried.steps_reset


def test_steps_keep_registry_order():
    # ace-web renders step rows in registry order and the plugin's fences walk
    # the map; a carried block must not reorder them.
    block, _ = _fork_block()
    registry = [
        "pdd-to-learn-app", "pdd-to-deliver-app", "app-deploy", "app-test", "training-materials",
    ]
    assert [n for n in block["steps"] if n in registry] == registry


def test_qa_and_eval_companions_follow_their_producer():
    # `<producer>-eval` / `<producer>-qa` are not registry rows, but the plugin
    # documents them as siblings of the producer, so they take its ordinal:
    # the learn-app eval is kept, the deploy qa is dropped.
    block, carried = _fork_block()
    assert block["steps"]["pdd-to-learn-app-eval"] == SOURCE_PHASE["steps"]["pdd-to-learn-app-eval"]
    assert "app-deploy-qa" not in block["steps"]
    assert "pdd-to-learn-app-eval" in carried.steps_carried
    assert "app-deploy-qa" in carried.steps_dropped


def test_a_step_the_registry_cannot_place_is_dropped_and_named():
    # The safe direction is the OPPOSITE of the artifact rule. An unattributed
    # FILE is kept (dropping loses data). An unattributed `done` STEP is
    # dropped (carrying it could skip work that must be redone; dropping only
    # costs a re-run). Either way the operator is told.
    block, carried = _fork_block()
    assert "mystery-step" not in block["steps"]
    assert "mystery-step" in carried.steps_dropped
    assert "mystery-step" in block["fork_note"]


def test_the_phase_is_in_progress_and_must_re_complete():
    block, carried = _fork_block()
    assert block["status"] == "in_progress"
    assert carried.status == "in_progress"
    # Not `null` — the plugin's validator rejects a non-string verdict, and a
    # present-but-null completed_at reads as a claim. Absent is the honest shape.
    for key in ("verdict", "completed_at", "summary_artifact", "started_at"):
        assert key not in block, key


def test_products_carry_whole_with_a_note_when_the_plugin_attributes_nothing():
    # The plugin's `lib/phase-products-schema.ts` types product blocks per
    # phase but names no producer, and `lib/artifact-manifest.ts`'s
    # `producedBy` attributes FILES. With nothing to attribute against, the
    # only honest move is to carry the block whole and SAY so — never guess
    # which sub-keys belong to the fork skill, never drop silently.
    block, carried = _fork_block()
    assert block["products"] == SOURCE_PHASE["products"]
    assert carried.products_attributed is False
    assert sorted(carried.products_keys_carried) == ["apps", "deployment"]
    assert carried.products_keys_dropped == ()
    assert "UNATTRIBUTED" in block["fork_note"]
    assert "apps" in block["fork_note"] and "deployment" in block["fork_note"]
    assert block["fork_note"] == carried.note


def test_products_carry_by_attribution_when_the_plugin_declares_producers(monkeypatch):
    # The seam for the day the plugin declares product-key producers: keys
    # owned by a lower-ordinal skill carry, keys owned by the fork skill or
    # later drop, keys the map does not cover are KEPT (a product pointer the
    # re-run overwrites is cheaper than a handoff a downstream phase cannot
    # find — same asymmetry as ace#1888).
    monkeypatch.setattr(
        "apps.opps.skills.product_producers",
        lambda phase: {"apps": "pdd-to-learn-app", "deployment": "app-deploy"},
    )
    source = copy.deepcopy(SOURCE_PHASE)
    source["products"]["unmapped"] = {"x": 1}
    block, carried = _fork_block(source)
    assert block["products"] == {"apps": SOURCE_PHASE["products"]["apps"], "unmapped": {"x": 1}}
    assert carried.products_attributed is True
    assert sorted(carried.products_keys_carried) == ["apps", "unmapped"]
    assert carried.products_keys_dropped == ("deployment",)
    assert "UNATTRIBUTED" not in block["fork_note"]
    assert "unmapped" in block["fork_note"]


def test_a_source_phase_with_no_products_gets_no_empty_key():
    source = copy.deepcopy(SOURCE_PHASE)
    del source["products"]
    block, carried = _fork_block(source)
    assert "products" not in block
    assert carried.products_keys_carried == ()


def test_a_fork_at_the_first_skill_of_a_phase_carries_nothing_and_is_pending():
    # Equivalent to a phase fork: nothing in the phase has a lower ordinal, so
    # even unattributed products cannot predate the fork skill and must drop.
    block, carried = _fork_block(skill="pdd-to-learn-app")
    assert carried.steps_carried == ()
    assert block["status"] == "pending"
    assert "products" not in block
    assert sorted(carried.products_keys_dropped) == ["apps", "deployment"]
    assert "dropped products keys" in block["fork_note"]
    assert all(v == {"status": "pending"} for v in block["steps"].values())


def test_a_legacy_string_step_status_is_normalized_not_carried_raw():
    source = copy.deepcopy(SOURCE_PHASE)
    source["steps"]["pdd-to-learn-app"] = "done"
    block, _ = _fork_block(source)
    assert block["steps"]["pdd-to-learn-app"] == {"status": "done"}


def test_an_earlier_step_the_source_never_recorded_is_pending():
    source = copy.deepcopy(SOURCE_PHASE)
    del source["steps"]["pdd-to-deliver-app"]
    block, carried = _fork_block(source)
    assert block["steps"]["pdd-to-deliver-app"] == {"status": "pending"}
    assert "pdd-to-deliver-app" in carried.steps_reset
    assert "pdd-to-deliver-app" not in carried.steps_carried


def test_carried_serializes_to_plain_json_shapes():
    _, carried = _fork_block()
    d = carried.as_dict()
    assert d["phase"] == "commcare-setup"
    assert d["fork_skill"] == "app-deploy"
    assert isinstance(d["steps_carried"], list)
    assert isinstance(d["products_keys_carried"], list)
    assert d["source_state_read"] is True
    assert d["note"] == carried.note


# ── the synthesized run_state as a whole ────────────────────────────


def _state(**kw) -> dict:
    return yaml.safe_load(
        _build_run_state_yaml(
            opp_slug="spark-facilitator",
            run_id="20260910-0541",
            owner_email="dev@example.com",
            fork_at_phase="commcare-setup",
            fork_ordinal=2,
            forked_from_run_id="20260909-1211",
            now_utc=NOW,
            **kw,
        )
    )


def test_the_skill_fork_block_replaces_the_fork_phase_only():
    block, _ = _fork_block()
    state = _state(
        skill_fork_block=block,
        source_products={"design-review": {"pdd": {"file_id": "1pdd"}}},
    )
    phases = state["phases"]
    assert phases["commcare-setup"]["status"] == "in_progress"
    assert phases["commcare-setup"]["steps"]["pdd-to-learn-app"]["status"] == "done"
    # Neighbours are untouched: the copied prefix is done + carries products,
    # everything after the fork phase is pending.
    assert phases["design-review"]["status"] == "done"
    assert phases["design-review"]["products"] == {"pdd": {"file_id": "1pdd"}}
    assert phases["connect-setup"]["status"] == "pending"
    assert state["current_phase"] == "commcare-setup"


# ── (b) a phase fork still resets the whole block ───────────────────


def test_a_phase_fork_still_resets_the_fork_phase_whole():
    state = _state(source_products={"commcare-setup": SOURCE_PHASE["products"]})
    block = state["phases"]["commcare-setup"]
    assert block["status"] == "pending"
    assert all(v == {"status": "pending"} for v in block["steps"].values())
    assert "products" not in block
    assert "fork_note" not in block


# ── (c) an unreadable source run_state degrades with a note ─────────


def _drive_with_run_state(body: str | None) -> MagicMock:
    drive = MagicMock()
    if body is None:
        drive.list_files.side_effect = lambda fid: []
        return drive
    rs = MagicMock()
    rs.id, rs.name, rs.mime_type = "rs", "run_state.yaml", "text/yaml"
    drive.list_files.side_effect = lambda fid: [rs]
    drive.get_content.side_effect = lambda fid, mime: MagicMock(content=body)
    return drive


@pytest.mark.parametrize(
    "body",
    [
        None,                       # no run_state.yaml in the source run
        "",                         # empty file
        "not: [a, mapping",         # malformed yaml
        "phases: null",             # no phases
        "phases: [1, 2]",           # phases is not a map
    ],
)
def test_an_unreadable_source_run_state_reads_as_none(body):
    assert _source_phase_blocks(_drive_with_run_state(body), "run-src") is None


def test_readable_blocks_come_back_whole_and_non_mappings_are_skipped():
    body = yaml.safe_dump({"phases": {"a": {"status": "done", "steps": {}}, "b": "x"}})
    assert _source_phase_blocks(_drive_with_run_state(body), "run-src") == {
        "a": {"status": "done", "steps": {}},
    }


def test_a_drive_error_reads_as_none_not_raised():
    drive = MagicMock()
    drive.list_files.side_effect = RuntimeError("drive is down")
    assert _source_phase_blocks(drive, "run-src") is None


def test_a_skill_fork_with_no_source_state_degrades_with_a_note():
    block, carried = _fork_block(None, read=False)
    assert block["status"] == "pending"
    assert all(v == {"status": "pending"} for v in block["steps"].values())
    assert "products" not in block
    assert carried.source_state_read is False
    assert carried.steps_carried == ()
    assert "run_state.yaml" in block["fork_note"]
    assert "nothing" in block["fork_note"].lower()


def test_a_skill_fork_whose_source_lacks_the_phase_degrades_with_a_note():
    # The source was readable but never reached this phase.
    block, carried = _fork_block(None, read=True)
    assert block["status"] == "pending"
    assert carried.source_state_read is True
    assert carried.steps_carried == ()
    assert "fork_note" in block


# ── fork_opp end to end (real state synthesis, fake Drive) ──────────


class _FakeFile:
    def __init__(self, id, name, mime_type, size=None):
        self.id = id
        self.name = name
        self.mime_type = mime_type
        self.size = size


FOLDER = "application/vnd.google-apps.folder"


def _fake_drive(source_run_state: str | None):
    run_root = [
        _FakeFile("p1", "1-design-review", FOLDER),
        _FakeFile("p2", "2-commcare", FOLDER),
    ]
    if source_run_state is not None:
        run_root.append(_FakeFile("rs", "run_state.yaml", "text/yaml", size=10))
    files = {
        "ace-root": [_FakeFile("source-opp", "source-opp", FOLDER)],
        "source-opp": [_FakeFile("runs", "runs", FOLDER)],
        "runs": [_FakeFile("run-source", "20260909-1211", FOLDER)],
        "run-source": run_root,
        "p1": [_FakeFile("a-pdd", "pdd.md", "text/markdown", size=10)],
        "p2": [
            _FakeFile("a-learn", "learn-app-summary.md", "text/markdown", size=10),
            _FakeFile("a-deploy", "deployment-summary.md", "text/markdown", size=10),
        ],
    }
    uploaded: dict[str, str] = {}
    ids = iter([f"new-{i}" for i in range(50)])
    drive = MagicMock()
    drive.list_files.side_effect = lambda fid: files.get(fid, [])
    drive.create_folder.side_effect = lambda parent, name: next(ids)
    drive.copy_file.side_effect = lambda src, dest, name: next(ids)
    drive.get_content.side_effect = (
        lambda fid, mime: MagicMock(content=source_run_state if fid == "rs" else "")
    )
    drive.get_text.side_effect = lambda fid: ""
    drive.update_file.side_effect = lambda fid, body, mime: fid

    def _upload(parent, name, body, mime):
        uploaded[name] = body
        return next(ids)

    drive.upload_file.side_effect = _upload
    drive.create_file.side_effect = _upload
    return drive, uploaded


def _run_fork(monkeypatch, source_run_state, **kwargs):
    drive, uploaded = _fake_drive(source_run_state)
    messages: list[dict] = []
    monkeypatch.setattr(
        "apps.opps.opp_forker.Session.create_with_owner",
        classmethod(lambda cls, **kw: MagicMock(id=1, pk=1, slug="sess")),
    )
    monkeypatch.setattr(
        "apps.opps.opp_forker.Message.objects.create",
        lambda **kw: messages.append(kw) or MagicMock(),
    )
    result = fork_opp(
        drive=drive,
        ace_root_folder_id="ace-root",
        owner=MagicMock(email="dev@example.com"),
        source_slug="source-opp",
        source_run_id="20260909-1211",
        now=NOW,
        **kwargs,
    )
    return result, uploaded, messages


SOURCE_RUN_STATE = yaml.safe_dump(
    {
        "opportunity": "source-opp",
        "run_id": "20260909-1211",
        "phases": {
            "design-review": {"status": "done", "products": {"pdd": {"file_id": "1pdd"}}},
            "commcare-setup": SOURCE_PHASE,
        },
    },
    sort_keys=False,
)


def test_fork_opp_writes_the_carried_phase_state(monkeypatch):
    result, uploaded, messages = _run_fork(
        monkeypatch, SOURCE_RUN_STATE, fork_at_skill="app-deploy",
    )
    state = yaml.safe_load(uploaded["run_state.yaml"])
    block = state["phases"]["commcare-setup"]
    assert block["status"] == "in_progress"
    assert block["steps"]["pdd-to-learn-app"]["file_id"] == "1learn"
    assert block["steps"]["app-deploy"] == {"status": "pending"}
    assert block["products"] == SOURCE_PHASE["products"]
    assert state["phases"]["design-review"]["products"] == {"pdd": {"file_id": "1pdd"}}

    # Recorded for the operator: on the result, and in the fork's audit turn.
    assert isinstance(result.carried, ForkCarried)
    assert result.carried.fork_skill == "app-deploy"
    system = next(m for m in messages if m.get("role") == "system")
    assert system["content"]["carried"] == result.carried.as_dict()
    assert "pdd-to-learn-app" in system["content"]["carried"]["steps_carried"]


def test_fork_opp_with_no_source_run_state_still_forks(monkeypatch):
    result, uploaded, _ = _run_fork(monkeypatch, None, fork_at_skill="app-deploy")
    state = yaml.safe_load(uploaded["run_state.yaml"])
    block = state["phases"]["commcare-setup"]
    assert block["status"] == "pending"
    assert result.carried is not None
    assert result.carried.source_state_read is False


def test_fork_opp_with_a_malformed_source_run_state_still_forks(monkeypatch):
    result, uploaded, _ = _run_fork(
        monkeypatch, "phases: [not, a, map", fork_at_skill="app-deploy",
    )
    assert "run_state.yaml" in uploaded
    assert result.carried is not None
    assert result.carried.source_state_read is False


def test_a_phase_fork_records_nothing_carried(monkeypatch):
    result, uploaded, messages = _run_fork(
        monkeypatch, SOURCE_RUN_STATE, fork_at_phase="commcare-setup",
    )
    assert result.carried is None
    state = yaml.safe_load(uploaded["run_state.yaml"])
    assert state["phases"]["commcare-setup"]["status"] == "pending"
    system = next(m for m in messages if m.get("role") == "system")
    assert system["content"]["carried"] is None
