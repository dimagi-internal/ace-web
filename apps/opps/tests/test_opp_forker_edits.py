"""Tests for fork-with-edits at the _rewrite_decisions_yaml seam."""
import yaml

from apps.opps.opp_forker import _rewrite_decisions_yaml


def _decisions_yaml(rows):
    return yaml.safe_dump({"decisions": rows}, sort_keys=False)


def test_rewrite_with_no_edits_matches_legacy_trim():
    """Existing callers (no edits) get current behavior.

    Phase names below are drawn from the stub plugin registry
    (see apps/opps/tests/fixtures/stub_plugin/agents/*.md) so that
    `_resolve_phase_ordinal` returns the expected ordinals during tests.
    """
    rows = [
        {"id": "a", "phase": "design-review", "default": "v1",
         "options_considered": [], "status": "applied"},
        {"id": "b", "phase": "commcare-setup", "default": "w1",
         "options_considered": [], "status": "applied"},
    ]
    src = _decisions_yaml(rows)

    out = _rewrite_decisions_yaml(src, fork_ordinal=2)  # keep ordinal < 2

    parsed = yaml.safe_load(out)
    ids = [r["id"] for r in parsed["decisions"]]
    assert ids == ["a"]  # 'b' belongs to phase ordinal 2, dropped


def test_rewrite_with_edits_applies_after_trim():
    rows = [
        {"id": "a", "phase": "design-review", "default": "v1",
         "options_considered": [], "status": "applied"},
    ]
    src = _decisions_yaml(rows)
    edits = [{"row_id": "a", "new_answer": "v2"}]

    out = _rewrite_decisions_yaml(src, fork_ordinal=8, edits=edits)

    parsed = yaml.safe_load(out)
    assert parsed["decisions"][0]["default"] == "v2"
    assert parsed["decisions"][0]["status"] == "overridden"
    assert "v1" in parsed["decisions"][0]["options_considered"]


def test_edits_targeting_trimmed_row_are_skipped():
    """If the edited row was trimmed because its phase >= fork point,
    the edit silently does nothing — the row no longer exists in the forked decisions.
    """
    rows = [
        {"id": "trimmed-row", "phase": "commcare-setup",
         "default": "v1", "options_considered": [], "status": "applied"},
    ]
    src = _decisions_yaml(rows)
    edits = [{"row_id": "trimmed-row", "new_answer": "v2"}]

    out = _rewrite_decisions_yaml(src, fork_ordinal=2, edits=edits)  # trims phase ordinal 2+

    parsed = yaml.safe_load(out)
    assert parsed["decisions"] == []
