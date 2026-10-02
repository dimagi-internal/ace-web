"""A fork RETIRES the decisions it re-runs instead of carrying them live
(dimagi-internal/ace#2582).

Evidence: ``spark-facilitator/20261001-2208`` was forked from
``20260926-1800`` at ``commcare-setup`` and started with the source run's
WHOLE ``decisions.yaml`` live — 33 rows from phases 4, 5 and 8 it had not
run, plus the Phase 3 rows it was about to re-make. Re-run producers append
under the same ids and ``decisions_append_rows`` skips an id that exists, so
the stale rows won; Phase 4 had to mint 27 ``-2208`` ids by hand.

Root cause: the trim resolved a row's ``phase`` through the AGENT registry
(``commcare-setup``), but the plugin's schema writes ``<N>-<kebab>`` tags
(``3-commcare``). No real row ever resolved, so "unknown phase → keep" kept
everything. Operator decision (2026-10-02): keep the history, but retire it.

The fixture is a subset of that run's real rows as the fork carried them in
(rows 0-116 of 20261001-2208's log, i.e. before its own Phase 3 appended
anything, with ``superseded_by`` links to rows it appended later removed).
"""
from pathlib import Path

import yaml

from apps.opps.opp_forker import _decision_row_ordinal, _rewrite_decisions_yaml

FIXTURE = Path(__file__).parent / "fixtures" / "decisions_spark_facilitator_20260926_1800.yaml"
SOURCE_RUN = "20260926-1800"
COMMCARE_ORDINAL = 3  # the real plugin's ordinal for commcare-setup / `3-commcare`


def _source() -> str:
    return FIXTURE.read_text()


def _fork(**kw):
    out = _rewrite_decisions_yaml(
        _source(), fork_ordinal=COMMCARE_ORDINAL, source_run_id=SOURCE_RUN, **kw,
    )
    return yaml.safe_load(out)


def _live(rows):
    return [r for r in rows if "superseded_by" not in r]


def test_numbered_phase_tags_resolve_to_their_ordinal():
    """The root cause, pinned: every tag the plugin writes resolves."""
    assert _decision_row_ordinal("1-design") == 1
    assert _decision_row_ordinal("3-commcare") == 3
    assert _decision_row_ordinal("8-solicitation-management") == 8


def test_fork_at_commcare_leaves_no_live_row_at_or_after_the_fork():
    """Before ace#2582 every one of these stayed live (FAILS on the old code)."""
    parsed = _fork()
    leaked = [
        r["id"] for r in _live(parsed["decisions"])
        if (_decision_row_ordinal(r["phase"]) or 0) >= COMMCARE_ORDINAL
    ]
    assert leaked == []


def test_history_is_kept_not_dropped():
    src = yaml.safe_load(_source())["decisions"]
    parsed = _fork()
    assert len(parsed["decisions"]) == len(src)
    by_id = {r["id"]: r for r in parsed["decisions"]}
    stale = by_id[f"deliver-latitude-payability-discriminator-{SOURCE_RUN}"]
    # The inherited value and its reasoning survive for the audit trail...
    original = next(r for r in src if r["id"] == "deliver-latitude-payability-discriminator")
    assert stale["ai-default"] == original["ai-default"]
    assert stale["reasoning"] == original["reasoning"]
    # ...marked with the plugin's existing supersession field, pointing at the
    # canonical id the re-run will append, plus where it came from.
    assert stale["superseded_by"] == "deliver-latitude-payability-discriminator"
    assert stale["inherited_from_run"] == SOURCE_RUN


def test_canonical_ids_are_free_for_the_re_run_producers():
    """`decisions_append_rows` skips an existing id — so the re-run's rows
    only land if the inherited ones moved off the canonical ids."""
    ids = {r["id"] for r in _fork()["decisions"]}
    for canonical in (
        "deliver-latitude-payability-discriminator",
        "learn-latitude-baseline-pretest",
        "program-reuse-vs-create",
        "connect-rule-meeting-conducted-yes",
        "system-prompt-baseline",
        "sol-solicitation-type",
    ):
        assert canonical not in ids


def test_an_in_phase_supersession_chain_survives_the_rename():
    """`learn-ambiguity-step-name-ampersand` → `...-verbatim` was a real
    in-run correction in Phase 3. Both are retired; the chain must still
    resolve between the archived ids, and its head points at its own
    canonical id."""
    by_id = {r["id"]: r for r in _fork()["decisions"]}
    old = by_id[f"learn-ambiguity-step-name-ampersand-{SOURCE_RUN}"]
    new = by_id[f"learn-ambiguity-step-name-ampersand-verbatim-{SOURCE_RUN}"]
    assert old["superseded_by"] == f"learn-ambiguity-step-name-ampersand-verbatim-{SOURCE_RUN}"
    assert new["supersedes"] == f"learn-ambiguity-step-name-ampersand-{SOURCE_RUN}"
    assert new["superseded_by"] == "learn-ambiguity-step-name-ampersand-verbatim"


def test_pre_fork_rows_stay_live_and_byte_identical():
    """Negative control: Phase 1 is not re-run, so its rows — including its
    own supersession chain — carry forward exactly as written."""
    src = yaml.safe_load(_source())["decisions"]
    parsed = _fork()["decisions"]
    pre_src = [r for r in src if r["phase"] == "1-design"]
    pre_out = [r for r in parsed if r["phase"] == "1-design"]
    assert pre_out == pre_src
    assert [r["id"] for r in _live(parsed)] == [
        "archetype-selection", "pilot-scope-window", "llo-payment-per-visit-revised",
    ]


def test_a_non_forked_rewrite_is_a_no_op():
    """Negative control: no fork point, default mode, no edits → nothing
    retired, nothing renamed."""
    src = yaml.safe_load(_source())
    out = yaml.safe_load(_rewrite_decisions_yaml(_source(), fork_ordinal=None))
    assert out["decisions"] == src["decisions"]


def test_human_rulings_at_or_after_the_fork_stay_live():
    rows = [
        {"id": "ruled", "phase": "4-connect", "ai-default": "x", "status": "human-decided",
         "decided_by": "a@dimagi.com", "decided_at": "2026-09-30"},
        {"id": "overridden", "phase": "4-connect", "ai-default": "x", "override": "y",
         "status": "overridden"},
        {"id": "default", "phase": "4-connect", "ai-default": "x", "status": "ai-default"},
    ]
    src = yaml.safe_dump({"schema_version": 5, "decisions": rows}, sort_keys=False)
    out = yaml.safe_load(_rewrite_decisions_yaml(
        src, fork_ordinal=COMMCARE_ORDINAL, source_run_id=SOURCE_RUN,
    ))
    assert [r["id"] for r in _live(out["decisions"])] == ["ruled", "overridden"]


def test_archived_id_collision_gets_a_counter():
    rows = [
        {"id": "x", "phase": "4-connect", "ai-default": "a", "status": "ai-default"},
        {"id": f"x-{SOURCE_RUN}", "phase": "1-design", "ai-default": "b",
         "status": "ai-default"},
    ]
    src = yaml.safe_dump({"schema_version": 5, "decisions": rows}, sort_keys=False)
    out = yaml.safe_load(_rewrite_decisions_yaml(
        src, fork_ordinal=COMMCARE_ORDINAL, source_run_id=SOURCE_RUN,
    ))
    assert [r["id"] for r in out["decisions"]] == [f"x-{SOURCE_RUN}-2", f"x-{SOURCE_RUN}"]


def test_skill_fork_keeps_the_fork_phase_s_earlier_skills_live():
    """A skill fork keeps that phase's earlier work, so it keeps those
    skills' decisions too. Stub registry: commcare-setup is ordinal 2 with
    pdd-to-learn-app < pdd-to-deliver-app < app-deploy."""
    from apps.opps.skills import resolve_fork_point

    point = resolve_fork_point(skill="app-deploy")
    rows = [
        {"id": "learn", "phase": "2-commcare", "skill": "pdd-to-learn-app",
         "ai-default": "a", "status": "ai-default"},
        {"id": "deploy", "phase": "2-commcare", "skill": "app-deploy",
         "ai-default": "a", "status": "ai-default"},
        {"id": "mystery", "phase": "2-commcare", "skill": "not-a-skill",
         "ai-default": "a", "status": "ai-default"},
    ]
    src = yaml.safe_dump({"schema_version": 5, "decisions": rows}, sort_keys=False)
    out = yaml.safe_load(_rewrite_decisions_yaml(
        src, fork_ordinal=point.phase_ordinal, source_run_id=SOURCE_RUN,
        fork_phase=point.phase, skill_fork_ordinal=point.skill_ordinal,
    ))
    assert [r["id"] for r in _live(out["decisions"])] == ["learn"]
