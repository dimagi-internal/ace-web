"""Pin _parse_decision_rows behavior across v1, v2, and v3 schemas.

The v3 schema (May 2026) renamed `options_considered` → `options` and
`notes` → `reasoning`. The v2 schema uses `ai-default` + optional
`override` with status enum `ai-default | overridden`. v1 used
`default` + `applied`/`open` statuses. The reader maps all three to
the same internal `Decision` shape and falls back: v3 fields first,
then v2, then v1. The reader also emits a warning log when a row has
an id but is missing question/ai-default — that's the regression
signature from the ACE 2026-05-25 hallucinated-field-names incident.
"""
import logging

from apps.opps.sync import _parse_decision_rows


def _base_row(extras: dict | None = None) -> dict:
    row = {
        "id": "row-1",
        "phase": "idea-to-design",
        "skill": "idea-to-pdd",
        "question": "Which language?",
        "options_considered": ["english", "french"],
        "source": "src",
        "notes": "",
    }
    if extras:
        row.update(extras)
    return row


def test_v1_row_maps_default_to_ai_default():
    rows = [_base_row({"default": "english", "status": "applied"})]
    [d] = _parse_decision_rows(rows)
    assert d.ai_default == "english"
    assert d.override == ""
    assert d.status == "ai-default"


def test_v1_open_status_maps_to_ai_default():
    rows = [_base_row({"default": "english", "status": "open"})]
    [d] = _parse_decision_rows(rows)
    assert d.status == "ai-default"


def test_v2_row_with_only_ai_default():
    rows = [_base_row({"ai-default": "english", "status": "ai-default"})]
    [d] = _parse_decision_rows(rows)
    assert d.ai_default == "english"
    assert d.override == ""
    assert d.status == "ai-default"


def test_v2_row_with_override():
    rows = [_base_row({
        "ai-default": "english",
        "override": "french",
        "status": "overridden",
    })]
    [d] = _parse_decision_rows(rows)
    assert d.ai_default == "english"
    assert d.override == "french"
    assert d.status == "overridden"


def test_row_with_neither_default_nor_ai_default_surfaces_empty():
    rows = [_base_row({"status": "ai-default"})]
    [d] = _parse_decision_rows(rows)
    assert d.ai_default == ""
    assert d.override == ""


def test_row_missing_id_is_dropped():
    rows = [_base_row({"id": "", "default": "x", "status": "ai-default"})]
    assert _parse_decision_rows(rows) == []


def test_non_dict_rows_are_dropped():
    assert _parse_decision_rows(["string", 42, None]) == []


def test_v3_row_reads_options_field():
    """v3 uses `options` (was v2 `options_considered`)."""
    row = {
        "id": "row-1",
        "phase": "1-design",
        "skill": "idea-to-pdd",
        "question": "Which language?",
        "ai-default": "english",
        "options": ["english", "french"],
        "source": "src",
        "status": "ai-default",
    }
    [d] = _parse_decision_rows([row])
    assert d.options_considered == ["english", "french"]


def test_v3_row_reads_reasoning_field():
    """v3 uses `reasoning` (was v2 `notes`); surface it as notes for the FE."""
    row = {
        "id": "row-1",
        "phase": "1-design",
        "skill": "idea-to-pdd",
        "question": "Which language?",
        "ai-default": "english",
        "options": [],
        "source": "src",
        "status": "ai-default",
        "reasoning": "english is the working language per LLO directory",
    }
    [d] = _parse_decision_rows([row])
    assert d.notes == "english is the working language per LLO directory"


def test_v2_options_considered_still_parses_for_back_compat():
    row = {
        "id": "row-1",
        "phase": "1-design",
        "skill": "idea-to-pdd",
        "question": "Which language?",
        "ai-default": "english",
        "options_considered": ["english", "french"],
        "source": "src",
        "status": "ai-default",
        "notes": "old-style reasoning",
    }
    [d] = _parse_decision_rows([row])
    assert d.options_considered == ["english", "french"]
    assert d.notes == "old-style reasoning"


def test_warns_when_row_has_id_but_missing_question(caplog):
    """The bednet-spot-check regression signature: id + phase but no
    question/ai-default because the writer used wrong field names. We
    surface the row (don't drop it) AND log a warning so CloudWatch
    catches the next occurrence."""
    bad_row = {
        "id": "wo-001",
        "phase": "idea-to-design",
        "skill": "pdd-to-work-order",
        "decision": "Payment rate set to TBD",  # ← wrong key
        "rationale": "Smoke test",  # ← wrong key
    }
    with caplog.at_level(logging.WARNING, logger="apps.opps.sync"):
        [d] = _parse_decision_rows([bad_row])
    assert d.id == "wo-001"
    assert d.question == ""
    assert d.ai_default == ""
    assert any(
        "wo-001" in record.message and "question" in record.message
        for record in caplog.records
    )


def test_no_warning_for_well_formed_row(caplog):
    row = {
        "id": "row-1",
        "phase": "1-design",
        "skill": "idea-to-pdd",
        "question": "Which language?",
        "ai-default": "english",
        "options": ["english"],
        "source": "src",
        "status": "ai-default",
    }
    with caplog.at_level(logging.WARNING, logger="apps.opps.sync"):
        _parse_decision_rows([row])
    assert not any("missing" in r.message for r in caplog.records)
