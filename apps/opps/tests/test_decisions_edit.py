"""Tests for apps.opps.decisions_edit.apply_edits_to_decisions_data
and upgrade_decisions_to_v3."""
from apps.opps.decisions_edit import (
    apply_edits_to_decisions_data,
    upgrade_decisions_to_v3,
)


def _row(row_id, ai_default, options=None, status="ai-default", **extras):
    row = {
        "id": row_id,
        "ai-default": ai_default,
        "options": list(options or []),
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
    data = {"decisions": [_row("a", "v1")]}
    edits = [{"row_id": "a", "new_answer": "v2"}]

    out = apply_edits_to_decisions_data(data, edits=edits)

    rows = out["decisions"]
    assert len(rows) == 1
    assert rows[0]["ai-default"] == "v1"
    assert rows[0]["override"] == "v2"
    assert rows[0]["status"] == "overridden"


def test_edit_matching_ai_default_clears_override():
    data = {"decisions": [
        _row("a", "v1", options=["v1", "v2"], status="overridden",
             override="v2"),
    ]}
    edits = [{"row_id": "a", "new_answer": "v1"}]

    out = apply_edits_to_decisions_data(data, edits=edits)

    assert "override" not in out["decisions"][0]
    assert out["decisions"][0]["status"] == "ai-default"


def test_edit_targeting_unknown_row_is_silently_ignored():
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
    out = apply_edits_to_decisions_data(
        {"foo": "bar"}, edits=[{"row_id": "a", "new_answer": "x"}],
    )
    assert out == {"foo": "bar"}


def test_edit_matching_ai_default_clears_override_reasoning():
    data = {"decisions": [
        _row("a", "v1", options=["v1", "v2"], status="overridden",
             override="v2", override_reasoning="user rationale"),
    ]}
    edits = [{"row_id": "a", "new_answer": "v1"}]

    out = apply_edits_to_decisions_data(data, edits=edits)

    assert "override" not in out["decisions"][0]
    assert "override_reasoning" not in out["decisions"][0]
    assert out["decisions"][0]["status"] == "ai-default"


def test_data_mutation_isolation():
    data = {"decisions": [_row("a", "v1")]}
    snapshot = {"decisions": [dict(data["decisions"][0])]}
    snapshot["decisions"][0]["options"] = list(
        data["decisions"][0]["options"]
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
    v3 = upgrade_decisions_to_v3(v1)
    assert v3["schema_version"] == 3
    row = v3["decisions"][0]
    assert "default" not in row
    assert row["ai-default"] == "v1"
    assert row["status"] == "ai-default"
    assert "options_considered" not in row
    assert row["options"] == []


def test_upgrade_v1_open_maps_to_ai_default():
    v1 = {
        "schema_version": 1,
        "decisions": [
            {"id": "a", "default": "v1", "options_considered": [],
             "status": "open", "phase": "design", "skill": "idea-to-pdd",
             "source": "x", "question": "q"},
        ],
    }
    v3 = upgrade_decisions_to_v3(v1)
    assert v3["decisions"][0]["status"] == "ai-default"


def test_upgrade_v1_overridden_row_copies_default_to_override():
    v1 = {
        "schema_version": 1,
        "decisions": [
            {"id": "a", "default": "v2", "options_considered": ["v1", "v2"],
             "status": "overridden", "phase": "design", "skill": "idea-to-pdd",
             "source": "x", "question": "q"},
        ],
    }
    v3 = upgrade_decisions_to_v3(v1)
    row = v3["decisions"][0]
    assert row["ai-default"] == "v2"
    assert row["override"] == "v2"
    assert row["status"] == "overridden"
    assert row["options"] == ["v1", "v2"]
    assert "options_considered" not in row


def test_upgrade_v2_renames_fields_to_v3():
    v2 = {
        "schema_version": 2,
        "decisions": [
            {"id": "a", "ai-default": "v1", "options_considered": ["v1", "v2"],
             "notes": "some rationale", "status": "ai-default",
             "phase": "design", "skill": "idea-to-pdd",
             "source": "x", "question": "q"},
        ],
    }
    v3 = upgrade_decisions_to_v3(v2)
    assert v3["schema_version"] == 3
    row = v3["decisions"][0]
    assert row["options"] == ["v1", "v2"]
    assert "options_considered" not in row
    assert row["reasoning"] == "some rationale"
    assert "notes" not in row


def test_upgrade_v3_is_idempotent():
    v3 = {
        "schema_version": 3,
        "decisions": [_row("a", "v1")],
    }
    out = upgrade_decisions_to_v3(v3)
    assert out["schema_version"] == 3
    assert out["decisions"][0]["ai-default"] == "v1"
