"""Tests for apps.opps.decisions_edit.apply_edits_to_decisions_data
and upgrade_decisions_v1_to_v2."""
from apps.opps.decisions_edit import (
    apply_edits_to_decisions_data,
    upgrade_decisions_v1_to_v2,
)


def _row(row_id, ai_default, options=None, status="applied", **extras):
    row = {
        "id": row_id,
        "ai-default": ai_default,
        "options_considered": list(options or []),
        "status": status,
        "phase": "design",
        "skill": "idea-to-pdd",
        "source": "idea-to-pdd",
        "question": f"q for {row_id}",
    }
    row.update(extras)
    return row


def test_no_edits_returns_data_unchanged():
    data = {"decisions": [_row("a", "v1")]}
    out = apply_edits_to_decisions_data(data, edits=[])
    assert out == data


def test_apply_single_edit_writes_override_field():
    """Edit populates `override:` and flips status; `ai-default:` is preserved."""
    data = {"decisions": [_row("a", "v1")]}
    edits = [{"row_id": "a", "new_answer": "v2"}]

    out = apply_edits_to_decisions_data(data, edits=edits)

    rows = out["decisions"]
    assert len(rows) == 1
    assert rows[0]["ai-default"] == "v1"   # immutable
    assert rows[0]["override"] == "v2"      # new field
    assert rows[0]["status"] == "overridden"


def test_edit_matching_ai_default_clears_override():
    """If the human reverts to the AI default, override is dropped and
    status flips back to applied."""
    data = {"decisions": [
        _row("a", "v1", options=["v1", "v2"], status="overridden",
             override="v2"),
    ]}
    edits = [{"row_id": "a", "new_answer": "v1"}]

    out = apply_edits_to_decisions_data(data, edits=edits)

    assert "override" not in out["decisions"][0]
    assert out["decisions"][0]["status"] == "applied"


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

    assert out["decisions"][0]["override"] == "v2"
    assert out["decisions"][1]["override"] == "w2"


def test_missing_decisions_key_returns_input_unchanged():
    """No 'decisions' field → can't apply edits, return as-is."""
    out = apply_edits_to_decisions_data(
        {"foo": "bar"}, edits=[{"row_id": "a", "new_answer": "x"}],
    )
    assert out == {"foo": "bar"}


def test_data_mutation_isolation():
    """Caller's dict shouldn't be mutated."""
    data = {"decisions": [_row("a", "v1")]}
    snapshot = {"decisions": [dict(data["decisions"][0])]}
    snapshot["decisions"][0]["options_considered"] = list(
        data["decisions"][0]["options_considered"]
    )

    apply_edits_to_decisions_data(
        data, edits=[{"row_id": "a", "new_answer": "v2"}],
    )

    assert data == snapshot, "input dict was mutated"


def test_upgrade_v1_renames_default_to_ai_default():
    v1 = {
        "schema_version": 1,
        "decisions": [
            {"id": "a", "default": "v1", "options_considered": [],
             "status": "applied", "phase": "design", "skill": "idea-to-pdd",
             "source": "x", "question": "q"},
        ],
    }
    v2 = upgrade_decisions_v1_to_v2(v1)
    assert v2["schema_version"] == 2
    row = v2["decisions"][0]
    assert "default" not in row
    assert row["ai-default"] == "v1"


def test_upgrade_v1_preserves_open_status():
    v1 = {
        "schema_version": 1,
        "decisions": [
            {"id": "a", "default": "v1", "options_considered": [],
             "status": "open", "phase": "design", "skill": "idea-to-pdd",
             "source": "x", "question": "q"},
        ],
    }
    v2 = upgrade_decisions_v1_to_v2(v1)
    assert v2["decisions"][0]["status"] == "open"


def test_upgrade_v1_overridden_row_copies_default_to_override():
    """v1 destroyed AI default on override; upgrade copies the value
    into both ai-default and override so the v2 invariant holds."""
    v1 = {
        "schema_version": 1,
        "decisions": [
            {"id": "a", "default": "v2", "options_considered": ["v1", "v2"],
             "status": "overridden", "phase": "design", "skill": "idea-to-pdd",
             "source": "x", "question": "q"},
        ],
    }
    v2 = upgrade_decisions_v1_to_v2(v1)
    row = v2["decisions"][0]
    assert row["ai-default"] == "v2"
    assert row["override"] == "v2"
    assert row["status"] == "overridden"


def test_upgrade_v2_is_idempotent():
    v2 = {
        "schema_version": 2,
        "decisions": [_row("a", "v1")],
    }
    out = upgrade_decisions_v1_to_v2(v2)
    assert out["schema_version"] == 2
    assert out["decisions"][0]["ai-default"] == "v1"
