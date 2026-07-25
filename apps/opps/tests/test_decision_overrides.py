"""Tests for the durable decision-overrides save path (issue #673, PR 2).

Covers the spec's contract from
docs/specs/2026-07-24-decision-review-save-design.md:

* POST reads the Redis buffer as the authoritative edit set (body carries
  no edits), joins each row against the run's decisions.yaml to recover
  phase / question / ai_default, and writes
  ``<opp>/inputs/decision-overrides.yaml``.
* Merge semantics: merge by ``id``, last write wins; a row whose override
  equals ``ai_default`` with no reasoning is dropped (revert leaves no
  trace beyond absence); successive saves against different runs merge
  cumulatively with per-row ``source_run_id`` provenance.
* Empty buffer is a no-op — no file write.
* Buffer clears on success.
* Read-side degradation: missing ``inputs/`` folder, missing file, and
  malformed YAML each yield "no saved overrides" rather than an error.

Patching follows docs/learnings/opps-access-module.md — patch on
``apps.opps.access.X``, not per-view modules.
"""
from unittest.mock import MagicMock

import pytest
import yaml

from apps.opps.decision_overrides import (
    OVERRIDES_FILENAME,
    fetch_saved_overrides,
    merge_overrides,
    save_decision_overrides,
)
from apps.opps.decisions_buffer import get_edits, set_edit
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def _decisions_yaml(rows):
    return yaml.safe_dump(
        {"schema_version": 2, "decisions": rows}, sort_keys=False,
    )


DECISION_ROWS = [
    {
        "id": "archetype-selection",
        "phase": "idea-to-design",
        "question": "Which delivery archetype best fits the intervention?",
        "ai-default": "atomic-visit",
        "options": ["atomic-visit", "focus-group"],
        "status": "ai-default",
    },
    {
        "id": "enrollment-unit",
        "phase": "idea-to-design",
        "question": "What is the enrollment unit?",
        "ai-default": "household",
        "options": ["household", "individual"],
        "status": "ai-default",
    },
]


def _drive_with_opp(slug="hh-poverty-targeting", run_id="20260722-1341",
                    inputs=None, decisions_rows=DECISION_ROWS):
    tree = {
        slug: {
            "opp.yaml": "slug: " + slug,
            "runs": {
                run_id: {
                    "decisions.yaml": _decisions_yaml(decisions_rows),
                },
            },
        },
    }
    if inputs is not None:
        tree[slug]["inputs"] = inputs
    return FakeDriveClient.from_tree(tree)


def _stage(slug, run_id, row_id, answer, reasoning="",
           email="expert@partner.org", name="Expert"):
    set_edit(
        slug, run_id, row_id=row_id, new_answer=answer,
        override_reasoning=reasoning, editor_email=email, editor_name=name,
    )


def _read_overrides_file(drive, slug):
    body = drive.get_content(
        drive.file_id(f"{slug}/inputs/{OVERRIDES_FILENAME}"), "application/x-yaml",
    ).content
    return yaml.safe_load(body)


SLUG = "hh-poverty-targeting"
RUN = "20260722-1341"


class TestSaveDecisionOverrides:
    def test_save_writes_file_with_denormalized_fields(self):
        drive = _drive_with_opp()
        _stage(SLUG, RUN, "archetype-selection", "focus-group",
               reasoning="Village-level enrollment")

        result = save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )

        data = _read_overrides_file(drive, SLUG)
        assert data["schema_version"] == 1
        assert data["kind"] == "decision-overrides"
        assert data["opp"] == SLUG
        assert data["updated_at"]
        rows = data["overrides"]
        assert len(rows) == 1
        row = rows[0]
        # Denormalized from the run's decisions.yaml — the file must
        # explain itself without resolving the run folder later.
        assert row["id"] == "archetype-selection"
        assert row["phase"] == "idea-to-design"
        assert row["question"] == (
            "Which delivery archetype best fits the intervention?"
        )
        assert row["ai_default"] == "atomic-visit"
        assert row["override"] == "focus-group"
        assert row["override_reasoning"] == "Village-level enrollment"
        assert row["decided_by"] == "expert@partner.org"
        assert row["decided_at"]
        assert row["source_run_id"] == RUN
        assert result["override_count"] == 1
        assert result["file_id"]

    def test_save_clears_buffer_on_success(self):
        drive = _drive_with_opp()
        _stage(SLUG, RUN, "archetype-selection", "focus-group")

        save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )

        assert get_edits(SLUG, RUN) == {}

    def test_empty_buffer_is_noop_not_empty_file_write(self):
        drive = _drive_with_opp()

        result = save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )

        assert result["override_count"] == 0
        assert result["file_id"] is None
        # No inputs/ folder was created, no file written.
        opp_children = {
            f.name for f in drive.list_files(drive.folder_id(SLUG))
        }
        assert "inputs" not in opp_children

    def test_second_save_merges_by_id_last_write_wins(self):
        drive = _drive_with_opp()
        _stage(SLUG, RUN, "archetype-selection", "focus-group", reasoning="first")
        save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )

        _stage(SLUG, RUN, "archetype-selection", "atomic-visit",
               reasoning="changed my mind — reaffirming the default")
        save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )

        rows = _read_overrides_file(drive, SLUG)["overrides"]
        assert len(rows) == 1
        assert rows[0]["override"] == "atomic-visit"
        assert rows[0]["override_reasoning"] == (
            "changed my mind — reaffirming the default"
        )

    def test_revert_drops_row_from_file(self):
        drive = _drive_with_opp()
        _stage(SLUG, RUN, "archetype-selection", "focus-group")
        _stage(SLUG, RUN, "enrollment-unit", "individual")
        save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )
        assert len(_read_overrides_file(drive, SLUG)["overrides"]) == 2

        # Staging the AI default with no reasoning is a revert — the row
        # must disappear from the file, leaving no trace beyond absence.
        _stage(SLUG, RUN, "archetype-selection", "atomic-visit")
        save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )

        rows = _read_overrides_file(drive, SLUG)["overrides"]
        assert [r["id"] for r in rows] == ["enrollment-unit"]

    def test_cumulative_merge_across_two_source_runs(self):
        run2 = "20260723-0900"
        drive = _drive_with_opp()
        # Second run exists with the same decisions log.
        runs_folder = drive.folder_id(f"{SLUG}/runs")
        run2_id = drive.create_folder(runs_folder, run2)
        drive.upload_file(
            run2_id, "decisions.yaml", _decisions_yaml(DECISION_ROWS),
            "application/x-yaml",
        )

        _stage(SLUG, RUN, "archetype-selection", "focus-group")
        save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )
        _stage(SLUG, run2, "enrollment-unit", "individual")
        save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=run2,
        )

        rows = _read_overrides_file(drive, SLUG)["overrides"]
        by_id = {r["id"]: r for r in rows}
        assert set(by_id) == {"archetype-selection", "enrollment-unit"}
        # Provenance survives per row, not per file.
        assert by_id["archetype-selection"]["source_run_id"] == RUN
        assert by_id["enrollment-unit"]["source_run_id"] == run2

    def test_buffered_row_missing_from_decisions_yaml_is_skipped(self):
        drive = _drive_with_opp()
        _stage(SLUG, RUN, "ghost-row", "whatever")
        _stage(SLUG, RUN, "archetype-selection", "focus-group")

        result = save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )

        rows = _read_overrides_file(drive, SLUG)["overrides"]
        assert [r["id"] for r in rows] == ["archetype-selection"]
        assert result["override_count"] == 1


class StrictMimeFakeDrive(FakeDriveClient):
    """Enforces the real GoogleDriveClient contract that the base fake
    ignores: ``get_content(file_id, mime_type)`` must receive the FILE'S
    actual mime type — Google-native files (Docs-typed YAML happens in
    real opps) are export-only, and a raw download 403s with
    ``fileNotDownloadable``. Caught live on bednet-spot-check (#673):
    hardcoding ``application/x-yaml`` blew up the save endpoint with 500.
    """

    GDOC = "application/vnd.google-apps.document"

    def make_gdoc(self, path: str) -> None:
        self._nodes_by_id[self.file_id(path)].mime_type = self.GDOC

    def get_content(self, file_id, mime_type):
        node = self._nodes_by_id[file_id]
        if node.mime_type == self.GDOC and mime_type != self.GDOC:
            raise RuntimeError(
                "fileNotDownloadable: Only files with binary content can be "
                "downloaded. Use Export with Docs Editors files.",
            )
        return super().get_content(file_id, mime_type)


class TestGoogleDocTypedFiles:
    def _gdoc_drive(self, **kwargs):
        drive = _drive_with_opp(**kwargs)
        strict = StrictMimeFakeDrive()
        # Adopt the built tree wholesale — same nodes, strict reads.
        strict._root = drive._root
        strict._nodes_by_id = drive._nodes_by_id
        strict._counter = drive._counter
        return strict

    def test_save_reads_gdoc_typed_decisions_yaml(self):
        drive = self._gdoc_drive()
        drive.make_gdoc(f"{SLUG}/runs/{RUN}/decisions.yaml")
        _stage(SLUG, RUN, "archetype-selection", "focus-group")

        result = save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )

        assert result["override_count"] == 1

    def test_save_reads_gdoc_typed_existing_overrides_file(self):
        drive = self._gdoc_drive()
        _stage(SLUG, RUN, "archetype-selection", "focus-group")
        save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )
        drive.make_gdoc(f"{SLUG}/inputs/{OVERRIDES_FILENAME}")

        _stage(SLUG, RUN, "enrollment-unit", "individual")
        result = save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )

        assert result["override_count"] == 2

    def test_fetch_reads_gdoc_typed_overrides_file(self):
        drive = self._gdoc_drive()
        _stage(SLUG, RUN, "archetype-selection", "focus-group")
        save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )
        drive.make_gdoc(f"{SLUG}/inputs/{OVERRIDES_FILENAME}")

        saved = fetch_saved_overrides(
            drive, opp_folder_id=drive.folder_id(SLUG),
        )
        assert set(saved) == {"archetype-selection"}


class TestMergeOverrides:
    def test_merge_by_id_last_write_wins(self):
        existing = [{"id": "a", "ai_default": "x", "override": "y"}]
        new = [{"id": "a", "ai_default": "x", "override": "z"}]
        merged = merge_overrides(existing, new)
        assert merged == [{"id": "a", "ai_default": "x", "override": "z"}]

    def test_revert_row_dropped_even_when_new(self):
        merged = merge_overrides(
            [], [{"id": "a", "ai_default": "x", "override": "x"}],
        )
        assert merged == []

    def test_equal_to_default_with_reasoning_is_kept(self):
        merged = merge_overrides(
            [],
            [{"id": "a", "ai_default": "x", "override": "x",
              "override_reasoning": "reaffirmed after review"}],
        )
        assert len(merged) == 1


class TestFetchSavedOverrides:
    def test_missing_inputs_folder_degrades_to_empty(self):
        drive = _drive_with_opp()
        assert fetch_saved_overrides(
            drive, opp_folder_id=drive.folder_id(SLUG),
        ) == {}

    def test_missing_file_degrades_to_empty(self):
        drive = _drive_with_opp(inputs={"other.md": "hi"})
        assert fetch_saved_overrides(
            drive, opp_folder_id=drive.folder_id(SLUG),
        ) == {}

    def test_malformed_yaml_degrades_to_empty(self):
        drive = _drive_with_opp(
            inputs={OVERRIDES_FILENAME: "overrides: [unclosed"},
        )
        assert fetch_saved_overrides(
            drive, opp_folder_id=drive.folder_id(SLUG),
        ) == {}

    def test_returns_rows_keyed_by_id(self):
        drive = _drive_with_opp()
        _stage(SLUG, RUN, "archetype-selection", "focus-group",
               reasoning="why not")
        save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )

        saved = fetch_saved_overrides(
            drive, opp_folder_id=drive.folder_id(SLUG),
        )
        assert set(saved) == {"archetype-selection"}
        row = saved["archetype-selection"]
        assert row["override"] == "focus-group"
        assert row["reasoning"] == "why not"
        assert row["decided_by"] == "expert@partner.org"
        assert row["source_run_id"] == RUN


class TestSavedOverridesOverlay:
    """The read-side overlay must be registered — the overrides file lives
    in a listing the Drive Changes API doesn't reliably invalidate."""

    def _overlay(self):
        from apps.opps.freshness_overlays import SNAPSHOT_OVERLAYS

        matches = [o for o in SNAPSHOT_OVERLAYS if o.name == "saved_overrides"]
        assert matches, "saved_overrides overlay is not registered"
        return matches[0]

    def test_overlay_refreshes_snapshot_from_drive(self):
        from types import SimpleNamespace

        from apps.opps.freshness_overlays import OverlayContext

        drive = _drive_with_opp()
        _stage(SLUG, RUN, "archetype-selection", "focus-group")
        save_decision_overrides(
            drive=drive, ace_root_folder_id="fake-root",
            opp_slug=SLUG, source_run_id=RUN,
        )
        snap = SimpleNamespace(
            opp_folder_id=drive.folder_id(SLUG), saved_overrides={},
        )

        self._overlay().apply(snap, drive, OverlayContext())

        assert "archetype-selection" in snap.saved_overrides

    def test_overlay_preserves_cached_value_on_drive_blip(self):
        from types import SimpleNamespace

        from apps.opps.freshness_overlays import OverlayContext

        cached = {"row-1": {"override": "keep-me"}}
        snap = SimpleNamespace(opp_folder_id="opp-1", saved_overrides=cached)

        class _BrokenClient:
            def list_files(self, *args, **kwargs):
                raise RuntimeError("Drive blip")

        self._overlay().apply(snap, _BrokenClient(), OverlayContext())

        assert snap.saved_overrides == cached

    def test_overlay_clears_when_file_legitimately_absent(self):
        from types import SimpleNamespace

        from apps.opps.freshness_overlays import OverlayContext

        drive = _drive_with_opp()  # no inputs/ folder at all
        snap = SimpleNamespace(
            opp_folder_id=drive.folder_id(SLUG),
            saved_overrides={"row-1": {"override": "stale"}},
        )

        self._overlay().apply(snap, drive, OverlayContext())

        assert snap.saved_overrides == {}


@pytest.mark.django_db
def test_endpoint_service_resolves_workspace_via_access_module(monkeypatch):
    """The api-level wrapper resolves the ACE root via apps.opps.access —
    patch there (opps-access-module learning), not on the view module."""
    try:
        from apps.opps.api import save_decision_overrides_and_return
        from apps.opps.schemas import DecisionOverridesSaveIn
    except ImportError as exc:
        pytest.skip(f"Schema deps not installed in this env: {exc}")

    drive = _drive_with_opp()
    _stage(SLUG, RUN, "archetype-selection", "focus-group")

    monkeypatch.setattr(
        "apps.opps.access.resolve_ace_root_folder_id",
        lambda ws: "fake-root",
    )
    monkeypatch.setattr(
        "apps.opps.drive_client.get_drive_client",
        lambda workspace: drive,
    )

    workspace = MagicMock()
    workspace.pk = "ws"
    body = DecisionOverridesSaveIn(source_run_id=RUN)

    result = save_decision_overrides_and_return(workspace, SLUG, body)

    assert result["override_count"] == 1
    assert get_edits(SLUG, RUN) == {}
    # No run was created — runs/ still contains only the source run.
    runs = {f.name for f in drive.list_files(drive.folder_id(f"{SLUG}/runs"))}
    assert runs == {RUN}
