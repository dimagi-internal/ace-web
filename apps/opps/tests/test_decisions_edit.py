"""Tests for apps.opps.decisions_edit.apply_edits_to_decisions_data."""
from apps.opps.decisions_edit import apply_edits_to_decisions_data


def _row(row_id, default, options=None, status="applied"):
    return {
        "id": row_id,
        "default": default,
        "options_considered": list(options or []),
        "status": status,
        "phase": "design",
        "skill": "idea-to-pdd",
        "source": "idea-to-pdd",
        "question": f"q for {row_id}",
    }


def test_no_edits_returns_data_unchanged():
    data = {"decisions": [_row("a", "v1")]}
    out = apply_edits_to_decisions_data(data, edits=[])
    assert out == data


def test_apply_single_edit_overrides_default_and_status():
    data = {"decisions": [_row("a", "v1")]}
    edits = [{"row_id": "a", "new_answer": "v2"}]

    out = apply_edits_to_decisions_data(data, edits=edits)

    rows = out["decisions"]
    assert len(rows) == 1
    assert rows[0]["default"] == "v2"
    assert rows[0]["status"] == "overridden"


def test_prior_default_preserved_in_options_considered():
    """Matches decisions-sync's contract: original default kept as an option."""
    data = {"decisions": [_row("a", "v1", options=["v1"])]}
    edits = [{"row_id": "a", "new_answer": "v2"}]

    out = apply_edits_to_decisions_data(data, edits=edits)

    assert "v1" in out["decisions"][0]["options_considered"]
    assert "v2" not in out["decisions"][0]["options_considered"]


def test_options_considered_dedup_on_repeat_override():
    """Re-overriding an already-overridden row preserves only the original default."""
    data = {"decisions": [_row("a", "v1", options=["v1"], status="overridden")]}
    edits = [{"row_id": "a", "new_answer": "v3"}]

    out = apply_edits_to_decisions_data(data, edits=edits)

    assert out["decisions"][0]["options_considered"] == ["v1"]
    assert out["decisions"][0]["default"] == "v3"
    assert out["decisions"][0]["status"] == "overridden"


def test_edit_targeting_unknown_row_is_silently_ignored():
    """Forker shouldn't synthesize new rows; unknown ids are no-ops."""
    data = {"decisions": [_row("a", "v1")]}
    edits = [{"row_id": "nope", "new_answer": "x"}]

    out = apply_edits_to_decisions_data(data, edits=edits)

    assert out == data


def test_multi_edit_applies_each():
    data = {"decisions": [_row("a", "v1"), _row("b", "w1")]}
    edits = [
        {"row_id": "a", "new_answer": "v2"},
        {"row_id": "b", "new_answer": "w2"},
    ]

    out = apply_edits_to_decisions_data(data, edits=edits)

    assert out["decisions"][0]["default"] == "v2"
    assert out["decisions"][1]["default"] == "w2"


def test_missing_decisions_key_returns_input_unchanged():
    """No 'decisions' field → can't apply edits, return as-is."""
    out = apply_edits_to_decisions_data({"foo": "bar"}, edits=[{"row_id": "a", "new_answer": "x"}])
    assert out == {"foo": "bar"}


def test_data_mutation_isolation():
    """Caller's dict shouldn't be mutated."""
    data = {"decisions": [_row("a", "v1")]}
    snapshot = {"decisions": [dict(data["decisions"][0])]}
    snapshot["decisions"][0]["options_considered"] = list(
        data["decisions"][0]["options_considered"]
    )

    apply_edits_to_decisions_data(data, edits=[{"row_id": "a", "new_answer": "v2"}])

    assert data == snapshot, "input dict was mutated"
