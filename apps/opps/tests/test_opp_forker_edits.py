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


"""Integration test: fork_opp() applies edits end-to-end via a fake DriveClient."""
import datetime as dt
from unittest.mock import MagicMock

from apps.opps.opp_forker import fork_opp


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
    import yaml

    source_body = yaml.safe_dump({
        "decisions": [
            {"id": "answer-1", "phase": "design-review", "default": "before",
             "options_considered": [], "status": "applied"},
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
    assert parsed["decisions"][0]["default"] == "after"
    assert parsed["decisions"][0]["status"] == "overridden"
    assert "before" in parsed["decisions"][0]["options_considered"]


def test_fork_opp_without_edits_unchanged_behavior(monkeypatch):
    """Backwards compat: fork_opp called without 'edits' kwarg works as before."""
    import yaml

    source_body = yaml.safe_dump({
        "decisions": [
            {"id": "answer-1", "phase": "design-review", "default": "v1",
             "options_considered": [], "status": "applied"},
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
    assert parsed["decisions"][0]["default"] == "v1"
    assert parsed["decisions"][0]["status"] == "applied"  # unchanged
