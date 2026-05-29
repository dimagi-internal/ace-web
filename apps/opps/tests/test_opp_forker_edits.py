"""Tests for fork-with-edits at the _rewrite_decisions_yaml seam.

Also includes an integration test: fork_opp() applies edits end-to-end
via a fake DriveClient.
"""
import datetime as dt
from unittest.mock import MagicMock

import yaml

from apps.opps.opp_forker import _rewrite_decisions_yaml, fork_opp


def _decisions_yaml(rows, *, schema_version=2):
    return yaml.safe_dump(
        {"schema_version": schema_version, "decisions": rows}, sort_keys=False,
    )


def test_rewrite_with_no_edits_matches_legacy_trim():
    """Existing callers (no edits) get current behavior.

    Phase names below are drawn from the stub plugin registry
    (see apps/opps/tests/fixtures/stub_plugin/agents/*.md) so that
    `_resolve_phase_ordinal` returns the expected ordinals during tests.
    """
    rows = [
        {"id": "a", "phase": "design-review", "ai-default": "v1",
         "options_considered": [], "status": "ai-default"},
        {"id": "b", "phase": "commcare-setup", "ai-default": "w1",
         "options_considered": [], "status": "ai-default"},
    ]
    src = _decisions_yaml(rows)

    out = _rewrite_decisions_yaml(src, fork_ordinal=2)  # keep ordinal < 2

    parsed = yaml.safe_load(out)
    ids = [r["id"] for r in parsed["decisions"]]
    assert ids == ["a"]  # 'b' belongs to phase ordinal 2, dropped


def test_rewrite_preserves_v4_evidence_basis_and_conflict_signals():
    """The fork trim copies surviving rows verbatim — the v4 fields
    (`evidence_basis`, `conflict_signals`) must pass through untouched so
    a forked run keeps the contested-fork signal."""
    rows = [
        {
            "id": "a",
            "phase": "design-review",
            "ai-default": "two linked forms",
            "options": ["one form", "two linked forms"],
            "status": "ai-default",
            "evidence_basis": "conflicting",
            "conflict_signals": ["visited twice", "one instrument only"],
        },
    ]
    src = _decisions_yaml(rows, schema_version=3)

    out = _rewrite_decisions_yaml(src, fork_ordinal=2)  # keep ordinal < 2

    row = yaml.safe_load(out)["decisions"][0]
    assert row["evidence_basis"] == "conflicting"
    assert row["conflict_signals"] == ["visited twice", "one instrument only"]


def test_rewrite_with_edits_applies_after_trim():
    rows = [
        {"id": "a", "phase": "design-review", "ai-default": "v1",
         "options_considered": [], "status": "ai-default"},
    ]
    src = _decisions_yaml(rows)
    edits = [{"row_id": "a", "new_answer": "v2"}]

    out = _rewrite_decisions_yaml(src, fork_ordinal=8, edits=edits)

    parsed = yaml.safe_load(out)
    row = parsed["decisions"][0]
    assert row["ai-default"] == "v1"   # immutable
    assert row["override"] == "v2"      # new override field
    assert row["status"] == "overridden"


def test_rewrite_edit_matching_ai_default_reverts_to_applied():
    """If the human enters a value matching the AI default, the override
    is cleared and status flips back to ai-default. Round-trip path."""
    rows = [
        {"id": "a", "phase": "design-review", "ai-default": "v1",
         "override": "v2", "options_considered": ["v1", "v2"],
         "status": "overridden"},
    ]
    src = _decisions_yaml(rows)
    edits = [{"row_id": "a", "new_answer": "v1"}]

    out = _rewrite_decisions_yaml(src, fork_ordinal=8, edits=edits)

    parsed = yaml.safe_load(out)
    row = parsed["decisions"][0]
    assert row["ai-default"] == "v1"
    assert "override" not in row
    assert row["status"] == "ai-default"


def test_edit_at_or_past_fork_point_survives_trim():
    """User edits are explicit human intent and survive the phase trim
    even when targeting a row whose phase would otherwise be dropped.

    This is the #544 fix: edits apply BEFORE the trim so the edited row
    flips to status=overridden, which is preserved through the trim.
    """
    rows = [
        {"id": "row-at-fork-phase", "phase": "commcare-setup",
         "ai-default": "v1", "options_considered": [], "status": "ai-default"},
    ]
    src = _decisions_yaml(rows)
    edits = [{"row_id": "row-at-fork-phase", "new_answer": "v2"}]

    out = _rewrite_decisions_yaml(src, fork_ordinal=2, edits=edits)

    parsed = yaml.safe_load(out)
    assert len(parsed["decisions"]) == 1
    assert parsed["decisions"][0]["override"] == "v2"
    assert parsed["decisions"][0]["status"] == "overridden"


def test_edit_targeting_unknown_row_id_is_silently_ignored():
    """The forker can't synthesize rows out of thin air; unknown row_ids
    are silently dropped. Distinct from the previous trim-skip behavior:
    here the row genuinely doesn't exist in the source."""
    rows = [
        {"id": "row-a", "phase": "design-review", "ai-default": "v1",
         "options_considered": [], "status": "ai-default"},
    ]
    src = _decisions_yaml(rows)
    edits = [{"row_id": "ghost-row", "new_answer": "v2"}]

    out = _rewrite_decisions_yaml(src, fork_ordinal=2, edits=edits)

    parsed = yaml.safe_load(out)
    # Just the original row, no synthesized ghost.
    ids = [r["id"] for r in parsed["decisions"]]
    assert ids == ["row-a"]


def test_keep_overrides_only_drops_applied_rows():
    """In keep-overrides-only mode, only status=overridden rows survive."""
    rows = [
        {"id": "applied-row", "phase": "design-review", "ai-default": "v1",
         "options_considered": [], "status": "ai-default"},
        {"id": "overridden-row", "phase": "design-review", "ai-default": "v1",
         "override": "v2", "options_considered": ["v1", "v2"],
         "status": "overridden"},
    ]
    src = _decisions_yaml(rows)

    out = _rewrite_decisions_yaml(
        src, fork_ordinal=8, mode="keep-overrides-only",
    )

    parsed = yaml.safe_load(out)
    ids = [r["id"] for r in parsed["decisions"]]
    assert ids == ["overridden-row"]


def test_keep_all_preserves_both_applied_and_overridden():
    """In keep-all mode (the default), every upstream row survives."""
    rows = [
        {"id": "applied-row", "phase": "design-review", "ai-default": "v1",
         "options_considered": [], "status": "ai-default"},
        {"id": "overridden-row", "phase": "design-review", "ai-default": "v1",
         "override": "v2", "options_considered": ["v1", "v2"],
         "status": "overridden"},
    ]
    src = _decisions_yaml(rows)

    out = _rewrite_decisions_yaml(src, fork_ordinal=8, mode="keep-all")

    parsed = yaml.safe_load(out)
    ids = sorted(r["id"] for r in parsed["decisions"])
    assert ids == ["applied-row", "overridden-row"]


def test_overridden_rows_survive_phase_trim_regardless_of_phase():
    """Overridden rows are explicit human intent and survive the phase
    trim regardless of which phase they belong to. They'll be honored
    when the relevant phase next runs (which is whatever decisions.yaml
    consumer-skill consumes them — re-running in this fork, or fresh in
    a later run)."""
    rows = [
        {"id": "upstream-override", "phase": "design-review",
         "ai-default": "v1", "override": "v2",
         "options_considered": ["v1", "v2"], "status": "overridden"},
        {"id": "downstream-override", "phase": "commcare-setup",
         "ai-default": "w1", "override": "w2",
         "options_considered": ["w1", "w2"], "status": "overridden"},
    ]
    src = _decisions_yaml(rows)

    out = _rewrite_decisions_yaml(
        src, fork_ordinal=2, mode="keep-overrides-only",
    )

    parsed = yaml.safe_load(out)
    ids = {r["id"] for r in parsed["decisions"]}
    # Both overrides survive: upstream-override is upstream of fork
    # (would survive anyway), downstream-override is downstream but
    # status=overridden grants survival regardless of phase.
    assert ids == {"upstream-override", "downstream-override"}


def test_non_overridden_downstream_rows_are_still_trimmed():
    """The override-survives carveout is just for overridden rows.
    AI-default rows from at/past the fork point still get trimmed."""
    rows = [
        {"id": "upstream-applied", "phase": "design-review",
         "ai-default": "v1", "options_considered": [], "status": "ai-default"},
        {"id": "downstream-applied", "phase": "commcare-setup",
         "ai-default": "w1", "options_considered": [], "status": "ai-default"},
    ]
    src = _decisions_yaml(rows)

    out = _rewrite_decisions_yaml(src, fork_ordinal=2)

    parsed = yaml.safe_load(out)
    ids = [r["id"] for r in parsed["decisions"]]
    assert ids == ["upstream-applied"]


def test_edit_at_fork_phase_survives_keep_overrides_only():
    """The #544 repro flow: user edits a Phase X row, forks at Phase X
    with mode=keep-overrides-only. The edit must produce exactly one
    surviving row in the new decisions.yaml — not zero, which was the
    pre-#544 bug.
    """
    rows = [
        {"id": "edited-row", "phase": "design-review", "ai-default": "v1",
         "options_considered": [], "status": "ai-default"},
        {"id": "other-row", "phase": "design-review", "ai-default": "x",
         "options_considered": [], "status": "ai-default"},
    ]
    src = _decisions_yaml(rows)
    edits = [{"row_id": "edited-row", "new_answer": "v2"}]

    out = _rewrite_decisions_yaml(
        src, fork_ordinal=1, edits=edits, mode="keep-overrides-only",
    )

    parsed = yaml.safe_load(out)
    assert len(parsed["decisions"]) == 1
    [row] = parsed["decisions"]
    assert row["id"] == "edited-row"
    assert row["override"] == "v2"
    assert row["status"] == "overridden"


def test_edit_at_fork_phase_survives_keep_all():
    """Same as above but with mode=keep-all. The edited row is overridden
    and survives the trim; non-edited rows in the fork phase are trimmed
    (they'll be re-derived on re-run)."""
    rows = [
        {"id": "edited-row", "phase": "design-review", "ai-default": "v1",
         "options_considered": [], "status": "ai-default"},
        {"id": "other-row", "phase": "design-review", "ai-default": "x",
         "options_considered": [], "status": "ai-default"},
    ]
    src = _decisions_yaml(rows)
    edits = [{"row_id": "edited-row", "new_answer": "v2"}]

    out = _rewrite_decisions_yaml(
        src, fork_ordinal=1, edits=edits, mode="keep-all",
    )

    parsed = yaml.safe_load(out)
    ids = [r["id"] for r in parsed["decisions"]]
    # Edited row survives via the overridden-survives carveout.
    # other-row gets trimmed (Phase ordinal 1 = fork_ordinal, no edit).
    assert ids == ["edited-row"]
    assert parsed["decisions"][0]["status"] == "overridden"


def test_pre_existing_override_in_fork_phase_also_survives():
    """An overridden row from an earlier fork survives a subsequent
    fork at the same phase. Cumulative-edit semantics."""
    rows = [
        {"id": "old-override", "phase": "design-review", "ai-default": "v1",
         "override": "v2", "options_considered": ["v1", "v2"],
         "status": "overridden"},
        {"id": "fresh-applied", "phase": "design-review", "ai-default": "x",
         "options_considered": [], "status": "ai-default"},
    ]
    src = _decisions_yaml(rows)

    out = _rewrite_decisions_yaml(src, fork_ordinal=1)

    parsed = yaml.safe_load(out)
    ids = [r["id"] for r in parsed["decisions"]]
    assert ids == ["old-override"]


def test_v1_input_upgrades_in_memory_on_rewrite():
    """v1-shape source decisions.yaml gets upgraded transparently.
    `default:` becomes `ai-default:`; old statuses map to `ai-default`."""
    rows = [
        {"id": "old-applied", "phase": "design-review", "default": "v1",
         "options_considered": [], "status": "ai-default"},
        {"id": "old-open", "phase": "design-review", "default": "w1",
         "options_considered": [], "status": "ai-default"},
    ]
    src = _decisions_yaml(rows, schema_version=1)

    out = _rewrite_decisions_yaml(src, fork_ordinal=8)

    parsed = yaml.safe_load(out)
    assert parsed["schema_version"] == 2
    for row in parsed["decisions"]:
        assert "default" not in row
        assert "ai-default" in row
    statuses = [r["status"] for r in parsed["decisions"]]
    assert statuses == ["ai-default", "ai-default"]


class _FakeFile:
    def __init__(self, id, name, mime_type, size=None):
        self.id = id
        self.name = name
        self.mime_type = mime_type
        self.size = size


def _build_fake_drive(decisions_body: str):
    """Minimal DriveClient stub: ace-root → source-opp → runs → run folder
    containing decisions.yaml + a phase folder.
    """
    folder_mime = "application/vnd.google-apps.folder"

    files = {
        "ace-root": [_FakeFile("source-opp", "source-opp", folder_mime)],
        "source-opp": [_FakeFile("runs", "runs", folder_mime)],
        "runs": [_FakeFile("run-source", "20260101-1000", folder_mime)],
        "run-source": [
            _FakeFile("decisions-src", "decisions.yaml", "text/yaml", size=len(decisions_body)),
            _FakeFile("phase-1-design-review", "1-design-review", folder_mime),
        ],
        "phase-1-design-review": [
            _FakeFile("artifact-1", "some-artifact.md", "text/markdown", size=10),
        ],
    }

    write_log = {"updated_decisions": None}
    next_id = iter([f"new-id-{i}" for i in range(50)])

    drive = MagicMock()
    drive.list_files.side_effect = lambda fid: files.get(fid, [])
    drive.create_folder.side_effect = lambda parent, name: next(next_id)
    drive.copy_file.side_effect = lambda src_id, dest_parent, name: next(next_id)
    drive.get_text.side_effect = lambda fid: decisions_body if fid == "decisions-src" else ""

    def _update_file(fid, body, mime):
        if "decisions" in fid or fid == "new-decisions":
            write_log["updated_decisions"] = body
        return fid
    drive.update_file.side_effect = _update_file

    def _create_file(parent, name, body, mime):
        return next(next_id)
    drive.create_file.side_effect = _create_file

    return drive, write_log


def _stub_post_rewrite_side_effects(monkeypatch):
    """Stub out the parts of fork_opp downstream of _rewrite_decisions_yaml
    that need real Django ORM objects (Session/Message creation) and a
    yaml-serializable owner (run_state.yaml synthesis). The seam under
    test is fork_opp → _rewrite_decisions_yaml; everything past it is
    out of scope for this test.
    """
    monkeypatch.setattr(
        "apps.opps.opp_forker._build_run_state_yaml",
        lambda **kw: "stub: run_state\n",
    )
    monkeypatch.setattr(
        "apps.opps.opp_forker.Session.create_with_owner",
        classmethod(lambda cls, **kw: MagicMock(id=1, pk=1)),
    )
    monkeypatch.setattr(
        "apps.opps.opp_forker.Message.objects.create",
        lambda **kw: MagicMock(),
    )


def test_fork_opp_passes_edits_to_rewrite(monkeypatch):
    """End-to-end seam test: fork_opp(edits=...) reaches _rewrite_decisions_yaml.

    Uses the stub plugin's 'commcare-setup' phase (ordinal 2) as the fork point;
    the row tagged 'design-review' (ordinal 1) survives the trim.
    """
    source_body = yaml.safe_dump({
        "schema_version": 2,
        "decisions": [
            {"id": "answer-1", "phase": "design-review", "ai-default": "before",
             "options_considered": [], "status": "ai-default"},
        ],
    })

    drive, write_log = _build_fake_drive(source_body)

    # Stub the subtree-copy and file-counter to focus on the edits plumbing.
    monkeypatch.setattr(
        "apps.opps.opp_forker._copy_run_subtree",
        lambda **kw: ("new-decisions", source_body),
    )
    monkeypatch.setattr(
        "apps.opps.opp_forker._count_files_to_copy",
        lambda *a, **kw: 1,
    )
    _stub_post_rewrite_side_effects(monkeypatch)

    owner = MagicMock()
    fork_opp(
        drive=drive,
        ace_root_folder_id="ace-root",
        owner=owner,
        source_slug="source-opp",
        fork_at_phase="commcare-setup",
        source_run_id="20260101-1000",
        workspace=None,
        edits=[{"row_id": "answer-1", "new_answer": "after"}],
        now=dt.datetime(2026, 5, 22, 12, 0, tzinfo=dt.UTC),
    )

    assert write_log["updated_decisions"] is not None
    parsed = yaml.safe_load(write_log["updated_decisions"])
    assert len(parsed["decisions"]) == 1
    row = parsed["decisions"][0]
    assert row["ai-default"] == "before"   # AI default preserved
    assert row["override"] == "after"       # override carries the edit
    assert row["status"] == "overridden"


def test_fork_opp_without_edits_unchanged_behavior(monkeypatch):
    """Backwards compat: fork_opp called without 'edits' kwarg works as before."""
    source_body = yaml.safe_dump({
        "schema_version": 2,
        "decisions": [
            {"id": "answer-1", "phase": "design-review", "ai-default": "v1",
             "options_considered": [], "status": "ai-default"},
        ],
    })

    drive, write_log = _build_fake_drive(source_body)

    monkeypatch.setattr(
        "apps.opps.opp_forker._copy_run_subtree",
        lambda **kw: ("new-decisions", source_body),
    )
    monkeypatch.setattr(
        "apps.opps.opp_forker._count_files_to_copy",
        lambda *a, **kw: 1,
    )
    _stub_post_rewrite_side_effects(monkeypatch)

    owner = MagicMock()
    fork_opp(
        drive=drive,
        ace_root_folder_id="ace-root",
        owner=owner,
        source_slug="source-opp",
        fork_at_phase="commcare-setup",
        source_run_id="20260101-1000",
        workspace=None,
        now=dt.datetime(2026, 5, 22, 12, 0, tzinfo=dt.UTC),
    )

    parsed = yaml.safe_load(write_log["updated_decisions"])
    assert parsed["decisions"][0]["ai-default"] == "v1"
    assert parsed["decisions"][0]["status"] == "ai-default"  # unchanged


def test_fork_opp_rejects_invalid_mode(monkeypatch):
    """The forker rejects unknown mode values with ForkOppError(invalid-mode)."""
    import pytest

    from apps.opps.opp_forker import ForkOppError

    source_body = yaml.safe_dump({"schema_version": 2, "decisions": []})
    drive, _ = _build_fake_drive(source_body)
    _stub_post_rewrite_side_effects(monkeypatch)

    owner = MagicMock()
    with pytest.raises(ForkOppError) as exc_info:
        fork_opp(
            drive=drive,
            ace_root_folder_id="ace-root",
            owner=owner,
            source_slug="source-opp",
            fork_at_phase="commcare-setup",
            source_run_id="20260101-1000",
            workspace=None,
            mode="with-feedback",  # legacy mode — no longer valid
            now=dt.datetime(2026, 5, 22, 12, 0, tzinfo=dt.UTC),
        )
    assert exc_info.value.code == "invalid-mode"
