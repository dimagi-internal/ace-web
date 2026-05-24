"""Pin _parse_decision_rows behavior across v1, v2, and v3 schemas.

The v3 schema uses `ai-default` + optional `override` with status enum
`ai-default | overridden`, `options` (was `options_considered`),
`reasoning` (was `notes`), and `override_reasoning` (new). The reader
maps all three schemas to `Decision` fields and normalizes old status
values (`applied`, `open`) to `ai-default`.
"""
from apps.opps.sync import _parse_decision_rows


def _base_row(extras: dict | None = None) -> dict:
    row = {
        "id": "row-1",
        "phase": "idea-to-design",
        "skill": "idea-to-pdd",
        "question": "Which language?",
        "options": ["english", "french"],
        "source": "src",
        "reasoning": "",
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


def test_v2_options_considered_falls_back():
    rows = [_base_row({
        "ai-default": "english",
        "status": "ai-default",
        "options_considered": ["english", "french"],
    })]
    # Remove v3 field so fallback is exercised
    del rows[0]["options"]
    del rows[0]["reasoning"]
    rows[0]["notes"] = "old note"
    [d] = _parse_decision_rows(rows)
    assert d.options == ["english", "french"]
    assert d.reasoning == "old note"


def test_v3_override_reasoning_parsed():
    rows = [_base_row({
        "ai-default": "english",
        "override": "french",
        "status": "overridden",
        "override_reasoning": "user rationale",
    })]
    [d] = _parse_decision_rows(rows)
    assert d.override_reasoning == "user rationale"
