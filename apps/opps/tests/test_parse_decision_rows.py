"""Pin _parse_decision_rows behavior across v1 and v2 schemas.

The writer in PR #541 introduced v2 (`ai-default` + optional `override`,
no `open` status). The reader must surface a single effective value to
the frontend regardless of which schema the source row uses.
"""
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


def test_v1_applied_row_surfaces_default_value():
    rows = [_base_row({"default": "english", "status": "applied"})]
    [d] = _parse_decision_rows(rows)
    assert d.default == "english"
    assert d.status == "applied"


def test_v1_open_status_collapses_to_applied():
    """`open` is a v1-only status; the v2 enum is {applied, overridden}.
    Reader collapses so the frontend sees the same status set regardless
    of which schema the source row used."""
    rows = [_base_row({"default": "english", "status": "open"})]
    [d] = _parse_decision_rows(rows)
    assert d.status == "applied"


def test_v2_row_with_only_ai_default_surfaces_ai_default():
    rows = [_base_row({"ai-default": "english", "status": "applied"})]
    [d] = _parse_decision_rows(rows)
    assert d.default == "english"
    assert d.status == "applied"


def test_v2_row_with_override_surfaces_override_not_ai_default():
    """When the human edited, the effective value is the override.
    `ai-default` is the immutable AI proposal, not what the user sees."""
    rows = [_base_row({
        "ai-default": "english",
        "override": "french",
        "status": "overridden",
    })]
    [d] = _parse_decision_rows(rows)
    assert d.default == "french"
    assert d.status == "overridden"


def test_row_with_neither_default_nor_ai_default_surfaces_empty():
    rows = [_base_row({"status": "applied"})]
    [d] = _parse_decision_rows(rows)
    assert d.default == ""


def test_row_missing_id_is_dropped():
    rows = [_base_row({"id": "", "default": "x", "status": "applied"})]
    assert _parse_decision_rows(rows) == []


def test_non_dict_rows_are_dropped():
    assert _parse_decision_rows(["string", 42, None]) == []
