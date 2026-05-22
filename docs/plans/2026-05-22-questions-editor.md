# Questions Editor + Edit-Aware Fork Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user edit decisions in the Phases view and fork the run with those edits applied atomically, so re-running the forked run regenerates downstream artifacts (PDD, work order, …) using the edited answers.

**Architecture:** Extend the existing fork endpoint (`POST /api/w/<ws>/opps/<slug>/fork`) with an optional `edits` payload. The backend applies edits to the trimmed `decisions.yaml` in the new run folder, setting `status: overridden` per the existing `decisions-sync` contract — Phase 1 skills already honor that status on re-run, so no new skill is needed. The frontend extends the existing read-only `DecisionsPanel` with inline edit affordances, lifts a local edit buffer to `PhaseView`, surfaces a sticky "Fork & re-run" action bar, and opens a new `ForkWithEditsDialog` (sibling to the existing `ForkOppDialog`) listing the artifacts the forked run will regenerate (computed via a manifest crosswalk on `row.source`).

**Tech Stack:** Django Ninja + Pydantic v2 (backend), React 19 + Vite + TypeScript + Tailwind (frontend), pytest + pytest-django (backend tests), vitest + @testing-library/react (frontend tests).

---

## Reference spec

`docs/specs/2026-05-22-questions-editor-design.md` — read first.

## File inventory

### Backend (create)
- `apps/opps/decisions_edit.py` — pure helpers: `apply_edits_to_decisions_data()` + tests
- `apps/system/manifest.py` — skill→products map helper
- `apps/opps/tests/test_decisions_edit.py`
- `apps/system/tests/test_manifest.py`

### Backend (modify)
- `apps/opps/schemas.py` — add `OppForkEditIn` + `edits` field on `OppForkIn`
- `apps/opps/opp_forker.py` — extend `_rewrite_decisions_yaml` + `fork_opp` to accept edits
- `apps/opps/api.py` — thread `body.edits` into `fork_opp_and_return`
- `apps/system/api.py` — add `GET /api/system/skill-products`

### Frontend (create)
- `frontend/src/components/views/decisions/decisionsReducer.ts` — local-buffer reducer
- `frontend/src/components/views/decisions/EditableDecisionRow.tsx` — extends DecisionRow with edit affordance
- `frontend/src/components/views/decisions/ForkWithEditsDialog.tsx` — save modal
- `frontend/src/components/views/decisions/PendingEditsBar.tsx` — sticky action bar
- `frontend/src/components/views/decisions/useSkillProducts.ts` — hook fetching manifest map
- `frontend/src/components/views/decisions/useAffectedDocs.ts` — derives unique affected paths
- `frontend/src/components/views/decisions/forkPoint.ts` — pure helper `computeForkPoint()`
- Vitest tests under `frontend/src/components/views/decisions/__tests__/`

### Frontend (modify)
- `frontend/src/components/views/DecisionsPanel.tsx` — accept edit props, render `EditableDecisionRow` when in edit mode
- `frontend/src/components/views/PhaseView.tsx` — lift reducer state, pass edit props, render `PendingEditsBar`
- `frontend/src/api/opps.ts` — extend `forkOpp()` body type with `edits`
- `frontend/src/api/types.ws.ts` — add `EditOp` type (or import from generated)

### Frontend (regenerated)
- `frontend/src/api/generated.ts` — OpenAPI regen after schema change

---

## Conventions used by this codebase

- **Tests live next to code**: `apps/opps/tests/test_*.py`. Run with `pytest -v <path>` from repo root.
- **Frontend tests**: `bun run test` from `frontend/`. Tests live under `__tests__/` sibling dirs.
- **Lint**: `ruff check .` for Python; frontend types checked via `bunx tsc -b`.
- **Commits**: small + frequent. After each TDD cycle.
- **Branch**: already on `emdash/questions-n4bts`. No need to create a new branch.

---

## Phase A — Backend forker accepts edits

### Task A1: Add `OppForkEditIn` schema + edits field on `OppForkIn`

**Files:**
- Modify: `apps/opps/schemas.py` (around line 138)
- Test: `apps/opps/tests/test_schemas.py` (create if missing)

- [ ] **Step 1: Write the failing test**

Create or append to `apps/opps/tests/test_schemas.py`:

```python
from apps.opps.schemas import OppForkIn, OppForkEditIn
import pytest


def test_opp_fork_in_accepts_no_edits():
    """Backwards compat: existing callers send no edits."""
    parsed = OppForkIn.model_validate({"fork_at_phase": "design"})
    assert parsed.fork_at_phase == "design"
    assert parsed.edits == []


def test_opp_fork_in_accepts_edits_list():
    parsed = OppForkIn.model_validate({
        "fork_at_phase": "design",
        "edits": [
            {"row_id": "pdd-target-population", "new_answer": "FLWs in rural Tanzania"},
        ],
    })
    assert len(parsed.edits) == 1
    assert parsed.edits[0].row_id == "pdd-target-population"
    assert parsed.edits[0].new_answer == "FLWs in rural Tanzania"


def test_opp_fork_edit_rejects_empty_row_id():
    with pytest.raises(Exception):  # pydantic ValidationError
        OppForkEditIn.model_validate({"row_id": "", "new_answer": "x"})


def test_opp_fork_edit_rejects_missing_new_answer():
    with pytest.raises(Exception):
        OppForkEditIn.model_validate({"row_id": "abc"})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/opps/tests/test_schemas.py -v
```
Expected: ImportError for `OppForkEditIn` (or AttributeError for `.edits`).

- [ ] **Step 3: Implement the schema change**

In `apps/opps/schemas.py`, locate the `# --- Fork ---` section (around line 135) and add `OppForkEditIn` before `OppForkIn`:

```python
class OppForkEditIn(StrictModel):
    """A single answer override to apply during fork.

    The forker finds the row by ``row_id`` in the source run's
    ``decisions.yaml``, sets its ``default`` to ``new_answer``, and
    marks ``status: overridden`` — matching the contract that
    ``decisions-sync`` already uses, so downstream phases on re-run
    honor the human's value verbatim.
    """

    row_id: str = Field(min_length=1)
    new_answer: str


class OppForkIn(StrictModel):
    fork_at_phase: str = Field(min_length=1)
    source_run_id: RunId | None = None
    edits: list[OppForkEditIn] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest apps/opps/tests/test_schemas.py -v
```
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/schemas.py apps/opps/tests/test_schemas.py
git commit -m "feat(opps): add edits payload to OppForkIn schema"
```

---

### Task A2: Pure helper `apply_edits_to_decisions_data()`

**Files:**
- Create: `apps/opps/decisions_edit.py`
- Test: `apps/opps/tests/test_decisions_edit.py`

The forker today does its trim inside `_rewrite_decisions_yaml`. We pull the edit-application logic into a sibling module so it's pure (dict-in/dict-out, no YAML) and easy to test.

- [ ] **Step 1: Write the failing test**

Create `apps/opps/tests/test_decisions_edit.py`:

```python
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
    assert "v2" not in out["decisions"][0]["options_considered"]  # new value is the default


def test_options_considered_dedup_on_repeat_override():
    """Re-overriding an already-overridden row preserves only the original default."""
    data = {"decisions": [_row("a", "v1", options=["v1"], status="overridden")]}
    edits = [{"row_id": "a", "new_answer": "v3"}]

    out = apply_edits_to_decisions_data(data, edits=edits)

    # v1 is the original; v2 was a previous override that's now gone; v3 is the new value.
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
    snapshot["decisions"][0]["options_considered"] = list(data["decisions"][0]["options_considered"])

    apply_edits_to_decisions_data(data, edits=[{"row_id": "a", "new_answer": "v2"}])

    assert data == snapshot, "input dict was mutated"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/opps/tests/test_decisions_edit.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `apps/opps/decisions_edit.py`:

```python
"""Apply human answer overrides to a parsed decisions.yaml dict.

Pure helper — no YAML, no Drive, no Django. Called from the forker
after the trim step. Matches the override contract used by the
``decisions-sync`` skill in the ACE plugin:

* ``default`` is set to the new value.
* ``status`` flips to ``"overridden"``.
* The pre-edit ``default`` value is preserved in ``options_considered``
  (deduplicated; only the *original* default is kept across repeat
  overrides — not the intermediate values).
"""
from __future__ import annotations

import copy
from typing import Any, Iterable


def apply_edits_to_decisions_data(
    data: dict[str, Any],
    *,
    edits: Iterable[dict[str, str]],
) -> dict[str, Any]:
    """Return a deep-copied dict with edits applied.

    Args:
        data: Parsed decisions.yaml as a dict (must contain ``decisions`` list).
        edits: Iterable of ``{"row_id": ..., "new_answer": ...}``.

    Unknown row_ids are silently ignored — the forker has no way to
    synthesize a new decision row out of thin air; the source must
    already contain it.
    """
    edits_list = list(edits)
    if not edits_list:
        return data

    rows = data.get("decisions")
    if not isinstance(rows, list):
        return data

    out = copy.deepcopy(data)
    out_rows = out["decisions"]

    edit_by_id = {e["row_id"]: e["new_answer"] for e in edits_list}

    for row in out_rows:
        if not isinstance(row, dict):
            continue
        row_id = row.get("id")
        if row_id not in edit_by_id:
            continue
        new_answer = edit_by_id[row_id]
        prior_default = row.get("default")
        options = row.get("options_considered") or []
        if not isinstance(options, list):
            options = []
        # Preserve the *original* default in options. If the row is already
        # overridden, its options list already contains the original — don't
        # add the intermediate value.
        if row.get("status") != "overridden":
            if prior_default is not None and prior_default not in options:
                options = [*options, prior_default]
        row["default"] = new_answer
        row["status"] = "overridden"
        row["options_considered"] = options

    return out
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest apps/opps/tests/test_decisions_edit.py -v
```
Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/decisions_edit.py apps/opps/tests/test_decisions_edit.py
git commit -m "feat(opps): apply_edits_to_decisions_data helper for fork-with-edits"
```

---

### Task A3: Wire helper into `_rewrite_decisions_yaml`

**Files:**
- Modify: `apps/opps/opp_forker.py:534-569`
- Test: `apps/opps/tests/test_opp_forker_edits.py` (new)

- [ ] **Step 1: Write the failing test**

Create `apps/opps/tests/test_opp_forker_edits.py`:

```python
"""Tests for fork-with-edits at the _rewrite_decisions_yaml seam."""
import yaml

from apps.opps.opp_forker import _rewrite_decisions_yaml


def _decisions_yaml(rows):
    return yaml.safe_dump({"decisions": rows}, sort_keys=False)


def test_rewrite_with_no_edits_matches_legacy_trim():
    """Existing callers (no edits) get current behavior."""
    rows = [
        {"id": "a", "phase": "design", "default": "v1",
         "options_considered": [], "status": "applied"},
        {"id": "b", "phase": "scenarios-and-acceptance", "default": "w1",
         "options_considered": [], "status": "applied"},
    ]
    src = _decisions_yaml(rows)

    out = _rewrite_decisions_yaml(src, fork_ordinal=2)  # keep ordinal < 2

    parsed = yaml.safe_load(out)
    ids = [r["id"] for r in parsed["decisions"]]
    assert ids == ["a"]  # 'b' belongs to phase ordinal 2, dropped


def test_rewrite_with_edits_applies_after_trim():
    rows = [
        {"id": "a", "phase": "design", "default": "v1",
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
    """If the edited row was trimmed because it belongs to a phase >= fork point,
    the edit is silently ignored — the row no longer exists in the forked decisions.
    """
    rows = [
        {"id": "trimmed-row", "phase": "scenarios-and-acceptance",
         "default": "v1", "options_considered": [], "status": "applied"},
    ]
    src = _decisions_yaml(rows)
    edits = [{"row_id": "trimmed-row", "new_answer": "v2"}]

    out = _rewrite_decisions_yaml(src, fork_ordinal=2, edits=edits)  # trims phase ordinal 2+

    parsed = yaml.safe_load(out)
    assert parsed["decisions"] == []  # row trimmed; edit has nothing to apply to
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/opps/tests/test_opp_forker_edits.py -v
```
Expected: TypeError ("unexpected keyword argument 'edits'") on the second + third tests.

- [ ] **Step 3: Modify `_rewrite_decisions_yaml`**

Edit `apps/opps/opp_forker.py`. Replace the existing function (around line 534) with:

```python
def _rewrite_decisions_yaml(
    original: str,
    *,
    fork_ordinal: int | None,
    edits: list[dict[str, str]] | None = None,
) -> str:
    """Trim ``decisions.yaml`` to rows from phases strictly before the fork,
    then apply any human answer edits.

    Each row carries its own ``phase`` tag (agent-declared phase name).
    Rows whose phase ordinal >= ``fork_ordinal`` are dropped. Rows whose
    phase isn't recognized stay (safer than silently dropping content
    when the registry / decisions file disagree).

    If ``edits`` is provided, each edit is applied to the trimmed rows
    via :func:`apps.opps.decisions_edit.apply_edits_to_decisions_data`.
    Edits whose ``row_id`` doesn't match any surviving row are silently
    ignored — either the row was trimmed (the user edited a row from a
    phase being re-run from scratch) or the id is bogus.
    """
    from apps.opps.decisions_edit import apply_edits_to_decisions_data

    if fork_ordinal is None and not edits:
        return original
    try:
        data = yaml.safe_load(original) or {}
        if not isinstance(data, dict):
            return original
    except yaml.YAMLError:
        return original

    rows = data.get("decisions")
    if not isinstance(rows, list):
        return original

    if fork_ordinal is not None:
        kept: list = []
        for row in rows:
            if not isinstance(row, dict):
                kept.append(row)
                continue
            phase_name = str(row.get("phase") or "").strip()
            if not phase_name:
                kept.append(row)
                continue
            ordinal = _resolve_phase_ordinal(phase_name)
            if ordinal is None or ordinal < fork_ordinal:
                kept.append(row)
        data["decisions"] = kept

    if edits:
        data = apply_edits_to_decisions_data(data, edits=edits)

    return yaml.safe_dump(data, sort_keys=False)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest apps/opps/tests/test_opp_forker_edits.py apps/opps/tests/test_decisions_edit.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/opp_forker.py apps/opps/tests/test_opp_forker_edits.py
git commit -m "feat(opps): _rewrite_decisions_yaml applies edits after trim"
```

---

### Task A4: Thread `edits` through `fork_opp()` and `_copy_run_subtree` callsite

**Files:**
- Modify: `apps/opps/opp_forker.py` — `fork_opp()` signature + body around line 199-202
- Test: append to `apps/opps/tests/test_opp_forker_edits.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/opps/tests/test_opp_forker_edits.py`:

```python
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
    """Minimal DriveClient stub that satisfies a single fork.

    Layout served:
        ace-root/
          source-opp/
            runs/
              20260101-1000/
                decisions.yaml  (text/yaml, body=decisions_body)
                1-design/
                  some-artifact.md
    """
    folder_mime = "application/vnd.google-apps.folder"

    files = {
        "ace-root": [_FakeFile("source-opp", "source-opp", folder_mime)],
        "source-opp": [_FakeFile("runs", "runs", folder_mime)],
        "runs": [_FakeFile("run-source", "20260101-1000", folder_mime)],
        "run-source": [
            _FakeFile("decisions-src", "decisions.yaml", "text/yaml", size=len(decisions_body)),
            _FakeFile("phase-1-design", "1-design", folder_mime),
        ],
        "phase-1-design": [
            _FakeFile("artifact-1", "some-artifact.md", "text/markdown", size=10),
        ],
    }

    write_log = {"updated_decisions": None}
    next_id = iter(["new-run-folder", "new-1-design", "new-decisions", "new-artifact",
                    "new-runstate", "_unused1", "_unused2", "_unused3"])

    drive = MagicMock()
    drive.list_files.side_effect = lambda fid: files.get(fid, [])
    drive.create_folder.side_effect = lambda parent, name: next(next_id)
    drive.copy_file.side_effect = lambda src_id, dest_parent, name: next(next_id)
    drive.get_text.side_effect = lambda fid: decisions_body if fid == "decisions-src" else ""

    def _update_file(fid, body, mime):
        if fid == "new-decisions":
            write_log["updated_decisions"] = body
        return fid
    drive.update_file.side_effect = _update_file

    def _create_file(parent, name, body, mime):
        return next(next_id)
    drive.create_file.side_effect = _create_file

    return drive, write_log


def test_fork_opp_passes_edits_to_rewrite(monkeypatch):
    """End-to-end via fake DriveClient: fork_opp(edits=...) → new run's
    decisions.yaml has the edit applied.
    """
    import yaml
    from apps.opps.opp_forker import _copy_run_subtree

    source_body = yaml.safe_dump({
        "decisions": [
            {"id": "answer-1", "phase": "design", "default": "before",
             "options_considered": [], "status": "applied"},
        ],
    })

    drive, write_log = _build_fake_drive(source_body)

    # Stub _copy_run_subtree to bypass the in-loop file walk and return
    # the dest id + source body our fake serves. We're testing the edits
    # plumbing, not the copy loop (covered elsewhere).
    monkeypatch.setattr(
        "apps.opps.opp_forker._copy_run_subtree",
        lambda **kw: ("new-decisions", source_body),
    )
    monkeypatch.setattr(
        "apps.opps.opp_forker._count_files_to_copy",
        lambda *a, **kw: 1,
    )

    owner = MagicMock()
    fork_opp(
        drive=drive,
        ace_root_folder_id="ace-root",
        owner=owner,
        source_slug="source-opp",
        fork_at_phase="design",
        source_run_id="20260101-1000",
        workspace=None,
        edits=[{"row_id": "answer-1", "new_answer": "after"}],
        now=dt.datetime(2026, 5, 22, 12, 0, tzinfo=dt.UTC),
    )

    assert write_log["updated_decisions"] is not None
    parsed = yaml.safe_load(write_log["updated_decisions"])
    # The edited row was for phase 'design' (ordinal 1); forking AT 'design'
    # means ordinal >= 1 gets trimmed. So the edit row is gone post-trim,
    # and the edit is a no-op. Verify the trim happened (row gone):
    assert parsed["decisions"] == []


def test_fork_opp_edits_apply_when_row_survives_trim(monkeypatch):
    """When the edited row is from a phase BEFORE the fork point, it
    survives the trim and the edit takes effect.
    """
    import yaml

    source_body = yaml.safe_dump({
        "decisions": [
            # phase 'design' = ordinal 1; we'll fork at scenarios (ordinal 2),
            # so this row survives.
            {"id": "answer-1", "phase": "design", "default": "before",
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

    owner = MagicMock()
    fork_opp(
        drive=drive,
        ace_root_folder_id="ace-root",
        owner=owner,
        source_slug="source-opp",
        fork_at_phase="scenarios-and-acceptance",
        source_run_id="20260101-1000",
        workspace=None,
        edits=[{"row_id": "answer-1", "new_answer": "after"}],
        now=dt.datetime(2026, 5, 22, 12, 0, tzinfo=dt.UTC),
    )

    parsed = yaml.safe_load(write_log["updated_decisions"])
    assert len(parsed["decisions"]) == 1
    assert parsed["decisions"][0]["default"] == "after"
    assert parsed["decisions"][0]["status"] == "overridden"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/opps/tests/test_opp_forker_edits.py::test_fork_opp_edits_apply_when_row_survives_trim -v
```
Expected: TypeError ("unexpected keyword argument 'edits'").

- [ ] **Step 3: Add `edits` parameter to `fork_opp()`**

Edit `apps/opps/opp_forker.py`. Locate `fork_opp()` signature (around line 83) and the call to `_rewrite_decisions_yaml` (around line 199). Make two changes:

(a) Add the parameter to the signature:

```python
def fork_opp(
    *,
    drive: DriveClient,
    ace_root_folder_id: str,
    owner,
    source_slug: str,
    fork_at_phase: str,
    source_run_id: str | None = None,
    workspace=None,
    progress_cb: ProgressCb | None = None,
    edits: list[dict[str, str]] | None = None,
    now: _dt.datetime | None = None,
) -> ForkOppResult:
```

(b) Pass `edits` to the rewrite call. Locate the existing block (around line 198-202):

```python
    if decisions_dest_id is not None:
        trimmed = _rewrite_decisions_yaml(
            decisions_source_body or "", fork_ordinal=fork_ordinal,
        )
        drive.update_file(decisions_dest_id, trimmed, "text/yaml")
```

Change to:

```python
    if decisions_dest_id is not None:
        trimmed = _rewrite_decisions_yaml(
            decisions_source_body or "",
            fork_ordinal=fork_ordinal,
            edits=edits,
        )
        drive.update_file(decisions_dest_id, trimmed, "text/yaml")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest apps/opps/tests/test_opp_forker_edits.py -v
```
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/opp_forker.py apps/opps/tests/test_opp_forker_edits.py
git commit -m "feat(opps): fork_opp accepts edits kwarg and threads through to rewrite"
```

---

### Task A5: Thread `edits` through the API endpoint

**Files:**
- Modify: `apps/opps/api.py` — `fork_opp_and_return()` around line 1172-1181
- Test: `apps/opps/tests/test_api_fork.py` (create if missing)

- [ ] **Step 1: Write the failing API integration test**

Create or append to `apps/opps/tests/test_api_fork.py`:

```python
"""Contract test: fork endpoint accepts edits payload and passes through."""
from unittest.mock import patch, MagicMock

import pytest
from django.test import Client


@pytest.fixture
def auth_client(db, django_user_model):
    """Authenticated client. Test workspace + member setup happens via
    the existing test fixtures the rest of apps/opps/tests use — adapt
    to whichever fixture file the project uses (see apps/opps/tests/conftest.py).
    """
    user = django_user_model.objects.create_user(
        email="forktest@example.com", password="x",
    )
    client = Client()
    client.force_login(user)
    return client, user


def test_fork_endpoint_accepts_edits(auth_client, db, settings):
    """POST /w/<ws>/opps/<slug>/fork with edits → forwarded to fork_opp."""
    client, _ = auth_client

    with patch("apps.opps.api.fork_opp_and_return") as mock_fork:
        mock_fork.return_value = {
            "slug": "test-opp",
            "run_id": "20260522-1300",
            "working_session_slug": "abc",
        }
        # Workspace setup omitted — replace with whatever fixture sets up
        # a workspace named 'dimagi' the user belongs to.
        response = client.post(
            "/api/w/dimagi/opps/test-opp/fork",
            data={
                "fork_at_phase": "design",
                "edits": [{"row_id": "a", "new_answer": "x"}],
            },
            content_type="application/json",
        )

    assert response.status_code == 201, response.content
    # Inspect the call: the OppForkIn body should carry the edits.
    call_kwargs = mock_fork.call_args
    body = call_kwargs.args[3] if len(call_kwargs.args) >= 4 else call_kwargs.kwargs["body"]
    assert len(body.edits) == 1
    assert body.edits[0].row_id == "a"
    assert body.edits[0].new_answer == "x"
```

NOTE: The exact workspace-setup fixture this project uses is in `apps/opps/tests/conftest.py` (or a higher-level conftest). If the test above doesn't find a workspace named `dimagi`, adapt to use whatever helper the existing fork tests use. Look at `apps/opps/tests/test_*fork*.py` for the right pattern.

- [ ] **Step 2: Run to verify it fails**

```bash
pytest apps/opps/tests/test_api_fork.py -v
```
Expected: failure either on workspace lookup (fixture) or assertion about `body.edits`.

- [ ] **Step 3: Modify `fork_opp_and_return()` to pass edits**

In `apps/opps/api.py`, locate `fork_opp_and_return()` (around line 1140). The `fork_opp(...)` call (around line 1172) needs `edits` passed through:

```python
    result = fork_opp(
        drive=drive,
        ace_root_folder_id=ace_folder_id,
        owner=user,
        source_slug=slug,
        fork_at_phase=body.fork_at_phase,
        source_run_id=source_run_id,
        workspace=workspace,
        progress_cb=_write_progress,
        edits=[e.model_dump() for e in body.edits] if body.edits else None,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest apps/opps/tests/test_api_fork.py -v
```
Expected: pass.

- [ ] **Step 5: Run the full opps test suite (regression check)**

```bash
pytest apps/opps/tests/ -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/opps/api.py apps/opps/tests/test_api_fork.py
git commit -m "feat(opps): API endpoint forwards edits payload to forker"
```

---

## Phase B — Backend skill-products endpoint

### Task B1: Skill→products map helper

**Files:**
- Create: `apps/system/manifest.py`
- Test: `apps/system/tests/test_manifest.py`

- [ ] **Step 1: Write the failing test**

Create `apps/system/tests/test_manifest.py`:

```python
"""Tests for apps.system.manifest.get_skill_products_map."""
from apps.system.manifest import build_skill_products_map


def test_build_map_groups_paths_by_produced_by():
    entries = [
        {"path": "1-design/idea-to-pdd.md", "produced_by": "idea-to-pdd"},
        {"path": "1-design/pdd-to-work-order.gdoc", "produced_by": "pdd-to-work-order"},
        {"path": "2-scenarios/scenarios.md", "produced_by": "scenarios-and-acceptance"},
    ]
    out = build_skill_products_map(entries)
    assert out == {
        "idea-to-pdd": ["1-design/idea-to-pdd.md"],
        "pdd-to-work-order": ["1-design/pdd-to-work-order.gdoc"],
        "scenarios-and-acceptance": ["2-scenarios/scenarios.md"],
    }


def test_build_map_collects_multi_product_skills():
    entries = [
        {"path": "1-design/a.md", "produced_by": "skill-x"},
        {"path": "1-design/b.md", "produced_by": "skill-x"},
    ]
    out = build_skill_products_map(entries)
    assert out == {"skill-x": ["1-design/a.md", "1-design/b.md"]}


def test_build_map_skips_entries_with_no_producer():
    """Some manifest rows describe inputs, not products — they have no produced_by."""
    entries = [
        {"path": "idea.md"},  # no produced_by
        {"path": "1-design/idea-to-pdd.md", "produced_by": "idea-to-pdd"},
    ]
    out = build_skill_products_map(entries)
    assert out == {"idea-to-pdd": ["1-design/idea-to-pdd.md"]}


def test_build_map_skips_entries_with_no_path():
    entries = [
        {"produced_by": "skill-x"},  # no path
    ]
    out = build_skill_products_map(entries)
    assert out == {}
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest apps/system/tests/test_manifest.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `apps/system/manifest.py`:

```python
"""Skill→products crosswalk derived from the ACE plugin artifact manifest.

The artifact manifest (``lib/artifact-manifest.ts`` in the ACE plugin)
declares which skill produces which file. This module turns that into
a lookup ``{skill_slug: [path, ...]}`` for the in-app decisions editor:
when the user edits a decision row, the editor needs to tell them which
files the forked re-run will regenerate, and that's the set of paths
the row's ``source`` skill produces.

Loaded once per process. Re-imports of the module (e.g. during tests)
re-read the manifest.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from apps.system import reader
from apps.system.parsers import parse_artifact_manifest

logger = logging.getLogger(__name__)


def build_skill_products_map(entries: list[dict]) -> dict[str, list[str]]:
    """Group manifest entries by ``produced_by`` skill slug.

    Entries without a ``produced_by`` or a ``path`` are skipped — they
    describe inputs, scratch files, or other non-product rows.
    """
    out: dict[str, list[str]] = {}
    for entry in entries:
        skill = entry.get("produced_by")
        path = entry.get("path")
        if not skill or not path:
            continue
        out.setdefault(skill, []).append(path)
    return out


@lru_cache(maxsize=1)
def get_skill_products_map() -> dict[str, list[str]]:
    """Return the {skill_slug: [path,...]} map, cached for the process lifetime."""
    try:
        ts_source = reader.read_artifact_manifest_source()
    except FileNotFoundError:
        logger.warning("Artifact manifest not found; skill→products map is empty")
        return {}
    entries = parse_artifact_manifest(ts_source)
    return build_skill_products_map(entries)
```

NOTE: `reader.read_artifact_manifest_source()` may not exist with that exact name. Check `apps/system/reader.py` — it has a function that returns the raw TS file content for `parse_artifact_manifest`. If named differently, adapt.

- [ ] **Step 4: Run to verify**

```bash
pytest apps/system/tests/test_manifest.py -v
```
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/system/manifest.py apps/system/tests/test_manifest.py
git commit -m "feat(system): build_skill_products_map helper from artifact manifest"
```

---

### Task B2: `GET /api/system/skill-products` endpoint

**Files:**
- Modify: `apps/system/api.py`
- Test: `apps/system/tests/test_api_skill_products.py` (new)

- [ ] **Step 1: Write the failing test**

Create `apps/system/tests/test_api_skill_products.py`:

```python
"""Test the GET /api/system/skill-products endpoint."""
from unittest.mock import patch

import pytest
from django.test import Client


def test_skill_products_endpoint_returns_map(db, django_user_model):
    user = django_user_model.objects.create_user(email="sptest@example.com", password="x")
    client = Client()
    client.force_login(user)

    fake_map = {
        "idea-to-pdd": ["1-design/idea-to-pdd.md"],
        "pdd-to-work-order": ["1-design/pdd-to-work-order.gdoc"],
    }
    with patch("apps.system.api.get_skill_products_map", return_value=fake_map):
        response = client.get("/api/system/skill-products")

    assert response.status_code == 200
    assert response.json() == fake_map


def test_skill_products_endpoint_requires_auth(db):
    client = Client()
    response = client.get("/api/system/skill-products")
    # Whatever the existing system endpoints return for unauth — usually 401 or 403
    assert response.status_code in (401, 403, 302)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest apps/system/tests/test_api_skill_products.py -v
```
Expected: 404 (endpoint doesn't exist yet).

- [ ] **Step 3: Add the endpoint**

In `apps/system/api.py`, add (mirror the style of the existing `@router.get` endpoints, around line 180):

```python
from apps.system.manifest import get_skill_products_map


@router.get(
    "/skill-products",
    summary="Skill → product paths map",
    description=(
        "Returns {skill_slug: [artifact_path, ...]} derived from the ACE "
        "plugin's artifact-manifest.ts. Used by the in-app decisions editor "
        "to show which files a forked re-run will regenerate."
    ),
)
def skill_products(request) -> dict[str, list[str]]:
    return get_skill_products_map()
```

- [ ] **Step 4: Run to verify it passes**

```bash
pytest apps/system/tests/test_api_skill_products.py -v
```
Expected: pass.

- [ ] **Step 5: Regen OpenAPI artifacts (frontend types)**

This project regenerates `frontend/src/api/generated.ts` from the OpenAPI schema. Find the command — usually one of:
- `make regen-openapi` (check `Makefile`)
- A workflow at `.github/workflows/regen-openapi.yml` (look there for the command)
- Or `python manage.py spectacular ...` / `python -m apps.api.openapi_export`

Run whichever command refreshes `frontend/src/api/generated.ts`. Verify the new endpoint shape appears in the diff.

- [ ] **Step 6: Commit**

```bash
git add apps/system/api.py apps/system/tests/test_api_skill_products.py frontend/src/api/generated.ts
git commit -m "feat(system): expose GET /api/system/skill-products"
```

---

## Phase C — Frontend reducer + hooks

### Task C1: `decisionsReducer` with edit buffer

**Files:**
- Create: `frontend/src/components/views/decisions/decisionsReducer.ts`
- Test: `frontend/src/components/views/decisions/__tests__/decisionsReducer.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/views/decisions/__tests__/decisionsReducer.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { decisionsReducer, initialDecisionsEditState, type DecisionsEditState } from "../decisionsReducer";

const empty: DecisionsEditState = initialDecisionsEditState();

describe("decisionsReducer", () => {
  it("APPLY_EDIT inserts a buffer entry keyed by row_id", () => {
    const state = decisionsReducer(empty, {
      type: "APPLY_EDIT",
      row_id: "a",
      new_answer: "v1",
    });
    expect(state.buffer).toEqual([{ row_id: "a", new_answer: "v1" }]);
  });

  it("APPLY_EDIT coalesces multiple edits to the same row_id", () => {
    let state = decisionsReducer(empty, { type: "APPLY_EDIT", row_id: "a", new_answer: "v1" });
    state = decisionsReducer(state, { type: "APPLY_EDIT", row_id: "a", new_answer: "v2" });
    expect(state.buffer).toEqual([{ row_id: "a", new_answer: "v2" }]);
  });

  it("APPLY_EDIT preserves order across distinct row_ids", () => {
    let state = decisionsReducer(empty, { type: "APPLY_EDIT", row_id: "a", new_answer: "v1" });
    state = decisionsReducer(state, { type: "APPLY_EDIT", row_id: "b", new_answer: "w1" });
    expect(state.buffer.map((e) => e.row_id)).toEqual(["a", "b"]);
  });

  it("REVERT_EDIT removes the row from the buffer", () => {
    let state = decisionsReducer(empty, { type: "APPLY_EDIT", row_id: "a", new_answer: "v1" });
    state = decisionsReducer(state, { type: "REVERT_EDIT", row_id: "a" });
    expect(state.buffer).toEqual([]);
  });

  it("REVERT_EDIT on a row_id not in buffer is a no-op", () => {
    const state = decisionsReducer(empty, { type: "REVERT_EDIT", row_id: "missing" });
    expect(state).toBe(empty);
  });

  it("DISCARD_ALL clears the buffer", () => {
    let state = decisionsReducer(empty, { type: "APPLY_EDIT", row_id: "a", new_answer: "v1" });
    state = decisionsReducer(state, { type: "APPLY_EDIT", row_id: "b", new_answer: "w1" });
    state = decisionsReducer(state, { type: "DISCARD_ALL" });
    expect(state.buffer).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd frontend && bun run test -- decisions/__tests__/decisionsReducer.test.ts
```
Expected: import failure.

- [ ] **Step 3: Implement**

Create `frontend/src/components/views/decisions/decisionsReducer.ts`:

```typescript
export interface EditOp {
  row_id: string;
  new_answer: string;
}

export interface DecisionsEditState {
  /** Buffered edits, coalesced by row_id, preserving insertion order. */
  buffer: EditOp[];
}

export function initialDecisionsEditState(): DecisionsEditState {
  return { buffer: [] };
}

export type DecisionsEditAction =
  | { type: "APPLY_EDIT"; row_id: string; new_answer: string }
  | { type: "REVERT_EDIT"; row_id: string }
  | { type: "DISCARD_ALL" };

export function decisionsReducer(
  state: DecisionsEditState,
  action: DecisionsEditAction,
): DecisionsEditState {
  switch (action.type) {
    case "APPLY_EDIT": {
      const existing = state.buffer.findIndex((e) => e.row_id === action.row_id);
      if (existing === -1) {
        return {
          buffer: [...state.buffer, { row_id: action.row_id, new_answer: action.new_answer }],
        };
      }
      const next = state.buffer.slice();
      next[existing] = { row_id: action.row_id, new_answer: action.new_answer };
      return { buffer: next };
    }
    case "REVERT_EDIT": {
      const idx = state.buffer.findIndex((e) => e.row_id === action.row_id);
      if (idx === -1) return state; // referential equality preserved
      return { buffer: state.buffer.filter((_, i) => i !== idx) };
    }
    case "DISCARD_ALL": {
      if (state.buffer.length === 0) return state;
      return { buffer: [] };
    }
  }
}

/** Build a Map<row_id, new_answer> from a buffer — used by render logic to
 * overlay edits on top of fetched decisions without mutating the source. */
export function bufferToMap(buffer: readonly EditOp[]): Map<string, string> {
  const m = new Map<string, string>();
  for (const e of buffer) m.set(e.row_id, e.new_answer);
  return m;
}
```

- [ ] **Step 4: Run to verify**

```bash
cd frontend && bun run test -- decisions/__tests__/decisionsReducer.test.ts
```
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/views/decisions/decisionsReducer.ts \
        frontend/src/components/views/decisions/__tests__/decisionsReducer.test.ts
git commit -m "feat(decisions): local-buffer edit reducer with coalesce + revert"
```

---

### Task C2: `useSkillProducts` hook + `useAffectedDocs` hook

**Files:**
- Create: `frontend/src/components/views/decisions/useSkillProducts.ts`
- Create: `frontend/src/components/views/decisions/useAffectedDocs.ts`
- Test: `frontend/src/components/views/decisions/__tests__/useAffectedDocs.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/views/decisions/__tests__/useAffectedDocs.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import type { Decision } from "@/api/types.ws";
import type { EditOp } from "../decisionsReducer";
import { computeAffectedDocs } from "../useAffectedDocs";

function dec(id: string, source: string): Decision {
  return {
    id,
    phase: "design",
    phase_raw: "design",
    skill: source,
    question: `q-${id}`,
    default: "v",
    options_considered: [],
    source,
    status: "applied",
    notes: "",
  };
}

const products = {
  "idea-to-pdd": ["1-design/idea-to-pdd.md"],
  "pdd-to-work-order": ["1-design/pdd-to-work-order.gdoc"],
};

describe("computeAffectedDocs", () => {
  it("returns empty when no edits", () => {
    const out = computeAffectedDocs({
      decisions: [dec("a", "idea-to-pdd")],
      edits: [],
      skillProducts: products,
    });
    expect(out).toEqual([]);
  });

  it("returns paths for the source skills of edited rows", () => {
    const decisions = [dec("a", "idea-to-pdd"), dec("b", "pdd-to-work-order")];
    const edits: EditOp[] = [
      { row_id: "a", new_answer: "x" },
      { row_id: "b", new_answer: "y" },
    ];
    const out = computeAffectedDocs({ decisions, edits, skillProducts: products });
    expect(out.sort()).toEqual([
      "1-design/idea-to-pdd.md",
      "1-design/pdd-to-work-order.gdoc",
    ]);
  });

  it("deduplicates when two edited rows share a source skill", () => {
    const decisions = [dec("a", "idea-to-pdd"), dec("b", "idea-to-pdd")];
    const edits: EditOp[] = [
      { row_id: "a", new_answer: "x" },
      { row_id: "b", new_answer: "y" },
    ];
    const out = computeAffectedDocs({ decisions, edits, skillProducts: products });
    expect(out).toEqual(["1-design/idea-to-pdd.md"]);
  });

  it("ignores edits whose row_id isn't in decisions", () => {
    const out = computeAffectedDocs({
      decisions: [dec("a", "idea-to-pdd")],
      edits: [{ row_id: "ghost", new_answer: "x" }],
      skillProducts: products,
    });
    expect(out).toEqual([]);
  });

  it("falls back gracefully when a source skill isn't in the products map", () => {
    const decisions = [dec("a", "unknown-skill")];
    const edits: EditOp[] = [{ row_id: "a", new_answer: "x" }];
    const out = computeAffectedDocs({ decisions, edits, skillProducts: products });
    // Returns the empty list — caller renders the fallback "phase outputs" line.
    expect(out).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd frontend && bun run test -- decisions/__tests__/useAffectedDocs.test.ts
```
Expected: import error.

- [ ] **Step 3: Implement both files**

Create `frontend/src/components/views/decisions/useSkillProducts.ts`:

```typescript
import { useEffect, useState } from "react";

const ENDPOINT = "/api/system/skill-products";

/** Cached, app-lifetime memoized fetch of the skill→products map. */
let cachedPromise: Promise<Record<string, string[]>> | null = null;

function fetchSkillProducts(): Promise<Record<string, string[]>> {
  if (!cachedPromise) {
    cachedPromise = fetch(ENDPOINT, { credentials: "include" }).then(async (r) => {
      if (!r.ok) throw new Error(`skill-products fetch failed: ${r.status}`);
      return (await r.json()) as Record<string, string[]>;
    });
  }
  return cachedPromise;
}

export function useSkillProducts(): Record<string, string[]> | null {
  const [data, setData] = useState<Record<string, string[]> | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchSkillProducts()
      .then((m) => {
        if (!cancelled) setData(m);
      })
      .catch((e) => {
        console.warn("useSkillProducts: load failed", e);
        if (!cancelled) setData({});
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return data;
}

/** Test seam: reset the module cache between tests. */
export function _resetSkillProductsCache() {
  cachedPromise = null;
}
```

Create `frontend/src/components/views/decisions/useAffectedDocs.ts`:

```typescript
import { useMemo } from "react";

import type { Decision } from "@/api/types.ws";
import type { EditOp } from "./decisionsReducer";
import { useSkillProducts } from "./useSkillProducts";

interface Args {
  decisions: readonly Decision[];
  edits: readonly EditOp[];
  skillProducts: Record<string, string[]>;
}

/** Pure: given edits, decisions, and the manifest map, return the unique
 * set of artifact paths the forked re-run will regenerate. Returns [] when
 * no edits, or when none of the edited rows' source skills are known. */
export function computeAffectedDocs({ decisions, edits, skillProducts }: Args): string[] {
  if (edits.length === 0) return [];

  const decisionById = new Map(decisions.map((d) => [d.id, d]));
  const seen = new Set<string>();

  for (const edit of edits) {
    const decision = decisionById.get(edit.row_id);
    if (!decision) continue;
    const paths = skillProducts[decision.source] ?? [];
    for (const p of paths) seen.add(p);
  }

  return Array.from(seen);
}

/** Hook wrapper: pulls the skill-products map and computes affected docs. */
export function useAffectedDocs(args: { decisions: readonly Decision[]; edits: readonly EditOp[] }) {
  const skillProducts = useSkillProducts();
  return useMemo(() => {
    if (skillProducts === null) return [];
    return computeAffectedDocs({
      decisions: args.decisions,
      edits: args.edits,
      skillProducts,
    });
  }, [args.decisions, args.edits, skillProducts]);
}
```

- [ ] **Step 4: Run tests to verify**

```bash
cd frontend && bun run test -- decisions/__tests__/useAffectedDocs.test.ts
```
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/views/decisions/useSkillProducts.ts \
        frontend/src/components/views/decisions/useAffectedDocs.ts \
        frontend/src/components/views/decisions/__tests__/useAffectedDocs.test.ts
git commit -m "feat(decisions): useSkillProducts + computeAffectedDocs hook"
```

---

### Task C3: `computeForkPoint` pure helper

**Files:**
- Create: `frontend/src/components/views/decisions/forkPoint.ts`
- Test: `frontend/src/components/views/decisions/__tests__/forkPoint.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/views/decisions/__tests__/forkPoint.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import type { Decision, PhaseInfo } from "@/api/types.ws";
import type { EditOp } from "../decisionsReducer";
import { computeForkPoint } from "../forkPoint";

const phases: PhaseInfo[] = [
  { name: "design", ordinal: 1, display_name: "Design" } as PhaseInfo,
  { name: "scenarios-and-acceptance", ordinal: 2, display_name: "Scenarios" } as PhaseInfo,
  { name: "ocs-setup", ordinal: 6, display_name: "OCS" } as PhaseInfo,
];

function dec(id: string, phase: string): Decision {
  return { id, phase, phase_raw: phase, skill: "x", question: "q", default: "v",
    options_considered: [], source: "x", status: "applied", notes: "" };
}

describe("computeForkPoint", () => {
  it("returns null when no edits", () => {
    expect(computeForkPoint({ decisions: [], edits: [], phases })).toBeNull();
  });

  it("returns the phase of a single edited row", () => {
    expect(computeForkPoint({
      decisions: [dec("a", "design")],
      edits: [{ row_id: "a", new_answer: "x" }],
      phases,
    })).toBe("design");
  });

  it("returns the lowest-ordinal phase across multiple edits", () => {
    expect(computeForkPoint({
      decisions: [dec("a", "design"), dec("b", "ocs-setup")],
      edits: [
        { row_id: "a", new_answer: "x" },
        { row_id: "b", new_answer: "y" },
      ],
      phases,
    })).toBe("design");
  });

  it("returns null when no edit row_id matches any decision", () => {
    expect(computeForkPoint({
      decisions: [dec("a", "design")],
      edits: [{ row_id: "ghost", new_answer: "x" }],
      phases,
    })).toBeNull();
  });

  it("ignores edits whose decision.phase isn't in the phases list", () => {
    expect(computeForkPoint({
      decisions: [dec("a", "unknown-phase")],
      edits: [{ row_id: "a", new_answer: "x" }],
      phases,
    })).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd frontend && bun run test -- decisions/__tests__/forkPoint.test.ts
```
Expected: import error.

- [ ] **Step 3: Implement**

Create `frontend/src/components/views/decisions/forkPoint.ts`:

```typescript
import type { Decision, PhaseInfo } from "@/api/types.ws";
import type { EditOp } from "./decisionsReducer";

interface Args {
  decisions: readonly Decision[];
  edits: readonly EditOp[];
  phases: readonly PhaseInfo[];
}

/** Default fork point = lowest phase ordinal across all edited rows.
 * Returns null when no edits or no edits map to known phases. */
export function computeForkPoint({ decisions, edits, phases }: Args): string | null {
  if (edits.length === 0) return null;

  const decisionById = new Map(decisions.map((d) => [d.id, d]));
  const ordinalByPhase = new Map(phases.map((p) => [p.name, p.ordinal]));

  let bestOrd: number | null = null;
  let bestName: string | null = null;

  for (const edit of edits) {
    const decision = decisionById.get(edit.row_id);
    if (!decision) continue;
    const ord = ordinalByPhase.get(decision.phase);
    if (ord === undefined) continue;
    if (bestOrd === null || ord < bestOrd) {
      bestOrd = ord;
      bestName = decision.phase;
    }
  }

  return bestName;
}
```

- [ ] **Step 4: Verify**

```bash
cd frontend && bun run test -- decisions/__tests__/forkPoint.test.ts
```
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/views/decisions/forkPoint.ts \
        frontend/src/components/views/decisions/__tests__/forkPoint.test.ts
git commit -m "feat(decisions): computeForkPoint default = lowest edited ordinal"
```

---

## Phase D — Frontend editable DecisionsPanel

### Task D1: Add edit props to existing `DecisionsPanel` + `DecisionRow`

`DecisionsPanel.tsx` already exists as a read-only viewer. We add optional edit props so callers can opt in. The read-only path is unaffected when no edit props are supplied.

**Files:**
- Modify: `frontend/src/components/views/DecisionsPanel.tsx`
- Test: `frontend/src/components/views/__tests__/DecisionsPanel.editable.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/views/__tests__/DecisionsPanel.editable.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Decision } from "@/api/types.ws";
import { DecisionsPanel } from "../DecisionsPanel";

function dec(over: Partial<Decision> = {}): Decision {
  return {
    id: "row-1",
    phase: "design",
    phase_raw: "design",
    skill: "idea-to-pdd",
    question: "Who is the target population?",
    default: "FLWs in rural Kenya",
    options_considered: [],
    source: "idea-to-pdd",
    status: "applied",
    notes: "",
    ...over,
  };
}

describe("DecisionsPanel — edit mode", () => {
  it("renders read-only when no onEdit prop", () => {
    render(<DecisionsPanel phase="design" decisions={[dec()]} />);
    // expand panel
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    // expand row
    fireEvent.click(screen.getByText("Who is the target population?"));
    // no editable input
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("renders edit affordance when onEdit prop is supplied", () => {
    const onEdit = vi.fn();
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[]}
        onEdit={onEdit}
        onRevert={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    fireEvent.click(screen.getByText("Who is the target population?"));
    // An "Edit" button or similar trigger exists.
    expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument();
  });

  it("clicking Edit reveals a textbox prefilled with the current default", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[]}
        onEdit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    fireEvent.click(screen.getByText("Who is the target population?"));
    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    const textbox = screen.getByRole("textbox") as HTMLInputElement | HTMLTextAreaElement;
    expect(textbox.value).toBe("FLWs in rural Kenya");
  });

  it("saving the textbox calls onEdit with row_id and new value", () => {
    const onEdit = vi.fn();
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[]}
        onEdit={onEdit}
        onRevert={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    fireEvent.click(screen.getByText("Who is the target population?"));
    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    const textbox = screen.getByRole("textbox");
    fireEvent.change(textbox, { target: { value: "FLWs in rural Tanzania" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(onEdit).toHaveBeenCalledWith("row-1", "FLWs in rural Tanzania");
  });

  it("shows an 'edited' badge and the effective value when row is in buffer", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[{ row_id: "row-1", new_answer: "FLWs in rural Tanzania" }]}
        onEdit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    // The row's summary shows the new value.
    expect(screen.getByText("FLWs in rural Tanzania")).toBeInTheDocument();
    // And an edited indicator (badge or icon).
    expect(screen.getByText(/edited/i)).toBeInTheDocument();
  });

  it("reverting calls onRevert with row_id", () => {
    const onRevert = vi.fn();
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[{ row_id: "row-1", new_answer: "FLWs in rural Tanzania" }]}
        onEdit={vi.fn()}
        onRevert={onRevert}
      />,
    );
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    fireEvent.click(screen.getByText("FLWs in rural Tanzania"));
    fireEvent.click(screen.getByRole("button", { name: /revert/i }));
    expect(onRevert).toHaveBeenCalledWith("row-1");
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd frontend && bun run test -- DecisionsPanel.editable
```
Expected: failures — the props don't exist yet.

- [ ] **Step 3: Add edit props + affordance**

Edit `frontend/src/components/views/DecisionsPanel.tsx`. Make these structural changes (keep the rest of the file intact):

(a) Update the `Props` interface and the parent component:

```typescript
import type { EditOp } from "./decisions/decisionsReducer";

interface Props {
  /** The phase whose decisions we want to show — match `Decision.phase`. */
  phase: string;
  /** All decisions on the run — we filter to this phase. */
  decisions: Decision[];
  /** Edit affordance opt-in: pass these together to enable editing. */
  editBuffer?: readonly EditOp[];
  onEdit?: (row_id: string, new_answer: string) => void;
  onRevert?: (row_id: string) => void;
}

export function DecisionsPanel({ phase, decisions, editBuffer, onEdit, onRevert }: Props) {
  const editable = !!(editBuffer && onEdit && onRevert);
  // ... existing filtering/sort ...
  return <DecisionsPanelInner
    phaseRows={phaseRows}
    open={open}
    overridden={overridden}
    editBuffer={editable ? editBuffer! : undefined}
    onEdit={editable ? onEdit : undefined}
    onRevert={editable ? onRevert : undefined}
  />;
}
```

(b) Thread props through `DecisionsPanelInner` and `DecisionRow`. Add an `EditableValue` subcomponent inside `DecisionRow`:

```typescript
function DecisionRow({
  decision,
  editBuffer,
  onEdit,
  onRevert,
}: {
  decision: Decision;
  editBuffer?: readonly EditOp[];
  onEdit?: (row_id: string, new_answer: string) => void;
  onRevert?: (row_id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const pendingEdit = editBuffer?.find((e) => e.row_id === decision.id);
  const effectiveValue = pendingEdit?.new_answer ?? decision.default;
  const isEdited = !!pendingEdit;

  // ... existing tone/badge ...

  return (
    <div>
      <button /* existing summary row */>
        {/* show effectiveValue + "edited" pill when isEdited */}
        {isEdited && (
          <span className="rounded-full border border-violet-500/40 bg-violet-500/10 px-2 py-0.5 text-[10px] text-violet-400">
            edited
          </span>
        )}
        {/* ... */}
      </button>
      {open && (
        <div /* existing detail grid */>
          {/* ... existing DetailRow components ... */}
          {onEdit && (
            <div className="col-span-2 mt-2 flex gap-2 border-t border-border/40 pt-3">
              {!editing && (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      setDraft(effectiveValue);
                      setEditing(true);
                    }}
                    className="rounded-md border border-border bg-background px-3 py-1 text-xs hover:bg-accent"
                  >
                    Edit
                  </button>
                  {isEdited && onRevert && (
                    <button
                      type="button"
                      onClick={() => onRevert(decision.id)}
                      className="rounded-md border border-border bg-background px-3 py-1 text-xs hover:bg-accent"
                    >
                      Revert
                    </button>
                  )}
                </>
              )}
              {editing && (
                <div className="flex w-full flex-col gap-2">
                  <textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    rows={3}
                    className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs"
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        onEdit(decision.id, draft);
                        setEditing(false);
                      }}
                      className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-400 hover:bg-emerald-500/20"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditing(false)}
                      className="rounded-md border border-border bg-background px-3 py-1 text-xs hover:bg-accent"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

The summary-row content that displays the "→ default" needs to display `effectiveValue` (so the panel-collapsed view reflects buffered edits). Locate the existing line:

```tsx
<span className="hidden truncate text-[11px] text-muted-foreground sm:block sm:max-w-[260px]">
  → <span className="font-medium text-foreground">{decision.default}</span>
</span>
```

Change `{decision.default}` to `{effectiveValue}`.

- [ ] **Step 4: Run tests to verify pass**

```bash
cd frontend && bun run test -- DecisionsPanel.editable
```
Expected: 6 tests pass.

- [ ] **Step 5: Run frontend typecheck**

```bash
cd frontend && bunx tsc -b
```
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/views/DecisionsPanel.tsx \
        frontend/src/components/views/__tests__/DecisionsPanel.editable.test.tsx
git commit -m "feat(decisions): add inline edit/revert affordance to DecisionsPanel"
```

---

## Phase E — PhaseView integration + sticky bar + modal

### Task E1: Sticky `PendingEditsBar` component

**Files:**
- Create: `frontend/src/components/views/decisions/PendingEditsBar.tsx`
- Test: `frontend/src/components/views/decisions/__tests__/PendingEditsBar.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/views/decisions/__tests__/PendingEditsBar.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PendingEditsBar } from "../PendingEditsBar";

describe("PendingEditsBar", () => {
  it("renders nothing when count is 0", () => {
    const { container } = render(
      <PendingEditsBar count={0} onDiscardAll={vi.fn()} onForkAndRerun={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows pluralized count and the two action buttons", () => {
    render(<PendingEditsBar count={3} onDiscardAll={vi.fn()} onForkAndRerun={vi.fn()} />);
    expect(screen.getByText(/3 pending edits/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /discard/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /fork & re-run/i })).toBeInTheDocument();
  });

  it("singular form when count is 1", () => {
    render(<PendingEditsBar count={1} onDiscardAll={vi.fn()} onForkAndRerun={vi.fn()} />);
    expect(screen.getByText(/1 pending edit\b/i)).toBeInTheDocument();
  });

  it("clicking Discard all calls onDiscardAll", () => {
    const onDiscardAll = vi.fn();
    render(<PendingEditsBar count={1} onDiscardAll={onDiscardAll} onForkAndRerun={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /discard/i }));
    expect(onDiscardAll).toHaveBeenCalledTimes(1);
  });

  it("clicking Fork & re-run calls onForkAndRerun", () => {
    const onFork = vi.fn();
    render(<PendingEditsBar count={1} onDiscardAll={vi.fn()} onForkAndRerun={onFork} />);
    fireEvent.click(screen.getByRole("button", { name: /fork & re-run/i }));
    expect(onFork).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd frontend && bun run test -- decisions/__tests__/PendingEditsBar
```
Expected: import error.

- [ ] **Step 3: Implement**

Create `frontend/src/components/views/decisions/PendingEditsBar.tsx`:

```tsx
import { GitFork, Undo2 } from "lucide-react";

interface Props {
  count: number;
  onDiscardAll: () => void;
  onForkAndRerun: () => void;
}

/**
 * Sticky action bar that appears at the bottom of the Phases view when the
 * user has buffered one or more decision edits. The "Fork & re-run" button
 * opens the ForkWithEditsDialog; nothing happens to the current run.
 */
export function PendingEditsBar({ count, onDiscardAll, onForkAndRerun }: Props) {
  if (count <= 0) return null;
  const noun = count === 1 ? "pending edit" : "pending edits";
  return (
    <div
      role="region"
      aria-label="Pending decision edits"
      className="sticky bottom-0 z-20 flex items-center gap-3 border-t border-border bg-background/95 px-4 py-3 backdrop-blur"
    >
      <span className="text-sm font-medium text-foreground">
        {count} {noun}
      </span>
      <div className="ml-auto flex gap-2">
        <button
          type="button"
          onClick={onDiscardAll}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs hover:bg-accent"
        >
          <Undo2 className="h-3.5 w-3.5" />
          Discard all
        </button>
        <button
          type="button"
          onClick={onForkAndRerun}
          className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-400 hover:bg-emerald-500/20"
        >
          <GitFork className="h-3.5 w-3.5" />
          Fork & re-run
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Verify**

```bash
cd frontend && bun run test -- decisions/__tests__/PendingEditsBar
```
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/views/decisions/PendingEditsBar.tsx \
        frontend/src/components/views/decisions/__tests__/PendingEditsBar.test.tsx
git commit -m "feat(decisions): PendingEditsBar sticky action bar"
```

---

### Task E2: Extend the API client for fork-with-edits

**Files:**
- Modify: `frontend/src/api/opps.ts` — `forkOpp()` body type

- [ ] **Step 1: Read current `forkOpp` signature**

```bash
grep -n "forkOpp\|fork_at_phase" frontend/src/api/opps.ts
```

Look at how the body is typed. It likely accepts `{ fork_at_phase: string; source_run_id?: string }`.

- [ ] **Step 2: Extend the body type**

In `frontend/src/api/opps.ts`, locate the `forkOpp()` function and its body type. Add the `edits` field:

```typescript
export interface ForkOppBody {
  fork_at_phase: string;
  source_run_id?: string | null;
  edits?: { row_id: string; new_answer: string }[];
}
```

(If the type lives inline in the function signature, lift it to a named interface as above.) Ensure the `fetch` call passes `edits` through if present.

- [ ] **Step 3: Run typecheck**

```bash
cd frontend && bunx tsc -b
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/opps.ts
git commit -m "feat(api): forkOpp body accepts optional edits payload"
```

---

### Task E3: `ForkWithEditsDialog` — the save modal

**Files:**
- Create: `frontend/src/components/views/decisions/ForkWithEditsDialog.tsx`
- Test: `frontend/src/components/views/decisions/__tests__/ForkWithEditsDialog.test.tsx`

This dialog is a sibling of the existing `ForkOppDialog` (`frontend/src/components/opps/ForkOppDialog.tsx`) — read that file to copy the visual style + the `forkOpp` + `getForkStatus` polling pattern. We're not reusing it directly because the props shape diverges enough (we add the affected-docs list and an editable fork-point dropdown) that a separate component is cleaner than overloading.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/views/decisions/__tests__/ForkWithEditsDialog.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PhaseInfo } from "@/api/types.ws";
import { ForkWithEditsDialog } from "../ForkWithEditsDialog";

const phases: PhaseInfo[] = [
  { name: "design", ordinal: 1, display_name: "Design" } as PhaseInfo,
  { name: "scenarios-and-acceptance", ordinal: 2, display_name: "Scenarios" } as PhaseInfo,
];

const baseProps = {
  open: true,
  onClose: vi.fn(),
  workspaceSlug: "dimagi",
  sourceSlug: "test-opp",
  sourceRunId: "20260101-1000",
  initialForkAtPhase: "design",
  phases,
  edits: [{ row_id: "a", new_answer: "v2" }],
  affectedDocs: ["1-design/idea-to-pdd.md", "1-design/pdd-to-work-order.gdoc"],
};

describe("ForkWithEditsDialog", () => {
  it("shows the affected docs list", () => {
    render(<ForkWithEditsDialog {...baseProps} />);
    expect(screen.getByText("1-design/idea-to-pdd.md")).toBeInTheDocument();
    expect(screen.getByText("1-design/pdd-to-work-order.gdoc")).toBeInTheDocument();
  });

  it("shows a fallback message when affected docs is empty", () => {
    render(<ForkWithEditsDialog {...baseProps} affectedDocs={[]} />);
    expect(screen.getByText(/will regenerate this phase's outputs/i)).toBeInTheDocument();
  });

  it("defaults fork point to initialForkAtPhase prop", () => {
    render(<ForkWithEditsDialog {...baseProps} />);
    const select = screen.getByLabelText(/fork point/i) as HTMLSelectElement;
    expect(select.value).toBe("design");
  });

  it("Cancel calls onClose", () => {
    const onClose = vi.fn();
    render(<ForkWithEditsDialog {...baseProps} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("Fork & re-run posts edits to the API", async () => {
    const forkSpy = vi.fn().mockResolvedValue({ slug: "test-opp", run_id: "20260522-1500" });
    render(<ForkWithEditsDialog {...baseProps} __forkOppForTest={forkSpy} />);
    fireEvent.click(screen.getByRole("button", { name: /fork & re-run/i }));
    await waitFor(() => expect(forkSpy).toHaveBeenCalled());
    expect(forkSpy).toHaveBeenCalledWith("dimagi", "test-opp", {
      fork_at_phase: "design",
      source_run_id: "20260101-1000",
      edits: [{ row_id: "a", new_answer: "v2" }],
    });
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd frontend && bun run test -- decisions/__tests__/ForkWithEditsDialog
```
Expected: import error.

- [ ] **Step 3: Implement**

Create `frontend/src/components/views/decisions/ForkWithEditsDialog.tsx`:

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { forkOpp, type ForkOppBody } from "@/api/opps";
import type { PhaseInfo } from "@/api/types.ws";
import type { EditOp } from "./decisionsReducer";

interface Props {
  open: boolean;
  onClose: () => void;
  workspaceSlug: string;
  sourceSlug: string;
  sourceRunId: string;
  /** Default fork point computed by computeForkPoint(). */
  initialForkAtPhase: string;
  phases: readonly PhaseInfo[];
  edits: readonly EditOp[];
  affectedDocs: readonly string[];
  /** Test seam: replace the forkOpp client call. */
  __forkOppForTest?: typeof forkOpp;
}

/**
 * Modal shown when the user confirms "Fork & re-run" with buffered
 * decision edits. Mirrors the visual style of ForkOppDialog. Lists the
 * artifacts the forked run will regenerate (derived from the manifest)
 * and lets the user pick the fork point if the auto-default isn't what
 * they want.
 */
export function ForkWithEditsDialog({
  open,
  onClose,
  workspaceSlug,
  sourceSlug,
  sourceRunId,
  initialForkAtPhase,
  phases,
  edits,
  affectedDocs,
  __forkOppForTest,
}: Props) {
  const [forkAtPhase, setForkAtPhase] = useState(initialForkAtPhase);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  if (!open) return null;

  const onSubmit = async () => {
    setSubmitting(true);
    setError(null);
    const body: ForkOppBody = {
      fork_at_phase: forkAtPhase,
      source_run_id: sourceRunId,
      edits: edits.map((e) => ({ row_id: e.row_id, new_answer: e.new_answer })),
    };
    try {
      const fn = __forkOppForTest ?? forkOpp;
      const result = await fn(workspaceSlug, sourceSlug, body);
      // Navigate to the new run's Phases view.
      navigate(
        `/w/${workspaceSlug}/opps/${result.slug}?run_id=${result.run_id}`,
      );
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div className="w-full max-w-lg rounded-lg border border-border bg-card p-5 shadow-xl">
        <h2 className="text-base font-semibold text-foreground">
          Fork run with {edits.length} answer change{edits.length === 1 ? "" : "s"}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Your edits touch <code className="rounded bg-muted/40 px-1">{initialForkAtPhase}</code>.
          The new run will re-run from there and regenerate:
        </p>

        <ul className="mt-3 space-y-1 text-xs">
          {affectedDocs.length === 0 && (
            <li className="text-muted-foreground italic">
              The new run will regenerate this phase's outputs.
            </li>
          )}
          {affectedDocs.map((path) => (
            <li key={path} className="font-mono text-foreground">
              • {path}
            </li>
          ))}
        </ul>

        <label className="mt-4 block text-xs">
          <span className="text-muted-foreground">Fork point</span>
          <select
            value={forkAtPhase}
            onChange={(e) => setForkAtPhase(e.target.value)}
            className="mt-1 block w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs"
          >
            {phases.map((p) => (
              <option key={p.name} value={p.name}>
                {p.ordinal}. {p.display_name || p.name}
              </option>
            ))}
          </select>
        </label>

        {error && (
          <div className="mt-3 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-400">
            {error}
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md border border-border bg-background px-3 py-1.5 text-xs hover:bg-accent disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={submitting}
            className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-50"
          >
            {submitting ? "Forking…" : "Fork & re-run"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Verify**

```bash
cd frontend && bun run test -- decisions/__tests__/ForkWithEditsDialog
```
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/views/decisions/ForkWithEditsDialog.tsx \
        frontend/src/components/views/decisions/__tests__/ForkWithEditsDialog.test.tsx
git commit -m "feat(decisions): ForkWithEditsDialog with affected-docs list"
```

---

### Task E4: Wire reducer + edits panel + bar + modal into `PhaseView`

**Files:**
- Modify: `frontend/src/components/views/PhaseView.tsx`

This is the "wire it all up" task. Read `PhaseView.tsx` end-to-end first (around 200 lines) before editing.

- [ ] **Step 1: Add reducer state to PhaseView**

At the top of `PhaseView`, add:

```typescript
import { useMemo, useReducer, useState } from "react";
// ... existing imports ...
import { decisionsReducer, initialDecisionsEditState } from "./decisions/decisionsReducer";
import { useAffectedDocs } from "./decisions/useAffectedDocs";
import { computeForkPoint } from "./decisions/forkPoint";
import { PendingEditsBar } from "./decisions/PendingEditsBar";
import { ForkWithEditsDialog } from "./decisions/ForkWithEditsDialog";

// inside PhaseView:
const [editState, dispatchEdit] = useReducer(decisionsReducer, undefined, initialDecisionsEditState);
const [forkDialogOpen, setForkDialogOpen] = useState(false);

const allDecisions = snapshot.current_run.decisions ?? [];
const affectedDocs = useAffectedDocs({ decisions: allDecisions, edits: editState.buffer });
const forkPoint = useMemo(
  () => computeForkPoint({ decisions: allDecisions, edits: editState.buffer, phases: snapshot.phases }),
  [allDecisions, editState.buffer, snapshot.phases],
);
```

- [ ] **Step 2: Pass edit props down to `DecisionsPanel`**

Find the `DecisionsPanel` usage in `PhaseView` (or in `PhaseTile` if that's where the panel is rendered). Add the three edit props:

```tsx
<DecisionsPanel
  phase={phase.name}
  decisions={phaseDecisions}
  editBuffer={editState.buffer}
  onEdit={(row_id, new_answer) =>
    dispatchEdit({ type: "APPLY_EDIT", row_id, new_answer })
  }
  onRevert={(row_id) => dispatchEdit({ type: "REVERT_EDIT", row_id })}
/>
```

Search PhaseView for *every* `DecisionsPanel` call site and update each.

- [ ] **Step 3: Render `PendingEditsBar` and `ForkWithEditsDialog`**

At the bottom of the component's JSX (just before the closing tag of the top-level container, after the existing `<aside>`/`<section>` block):

```tsx
<PendingEditsBar
  count={editState.buffer.length}
  onDiscardAll={() => dispatchEdit({ type: "DISCARD_ALL" })}
  onForkAndRerun={() => setForkDialogOpen(true)}
/>
{forkDialogOpen && forkPoint && (
  <ForkWithEditsDialog
    open={forkDialogOpen}
    onClose={() => setForkDialogOpen(false)}
    workspaceSlug={/* read from URL params; see other dialogs */}
    sourceSlug={oppSlug}
    sourceRunId={snapshot.current_run.run_id}
    initialForkAtPhase={forkPoint}
    phases={snapshot.phases}
    edits={editState.buffer}
    affectedDocs={affectedDocs}
  />
)}
```

Look at how other components in this file read `workspaceSlug` — usually via `useParams<{ workspaceSlug: string }>()` from react-router-dom. If not already imported, add it.

- [ ] **Step 4: Run typecheck**

```bash
cd frontend && bunx tsc -b
```
Expected: clean.

- [ ] **Step 5: Manual smoke**

Spin up the dev server and load a real opp's Phases view:

```bash
docker compose up   # or however dev runs locally
```

Open `http://localhost:8000/w/<ws>/opps/<slug>` (or the relevant route in dev), find a phase with decisions, expand the panel, click a row, click Edit, change the value, Save. Verify:
- The summary shows the new value + an "edited" badge
- The sticky bar at the bottom shows "1 pending edit" with Discard all + Fork & re-run
- Clicking Fork & re-run opens the dialog with the affected docs list
- Cancel closes the dialog without effects

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/views/PhaseView.tsx
git commit -m "feat(views): wire decisions editor into PhaseView"
```

---

## Phase F — Verification + smoke

### Task F1: Confirm manifest's products entries for Phase 1 skills are clean

**Files:**
- Optionally update: `apps/system/manifest.py` (add filter)

- [ ] **Step 1: Read the manifest**

```bash
cat $ACE_PLUGIN_PATH/lib/artifact-manifest.ts | head -200
```
(Or wherever `ACE_PLUGIN_PATH` resolves — see `apps/system/reader.py` for how the path is computed.)

- [ ] **Step 2: Inspect Phase 1 entries**

Find every entry with `producedBy: "idea-to-pdd"` and `producedBy: "pdd-to-work-order"`. Confirm:
- `idea-to-pdd` produces `1-design/idea-to-pdd.md`
- `pdd-to-work-order` produces `1-design/pdd-to-work-order.gdoc`

Look for any other entries under those skills. If a skill is listed as producer for orchestration files (e.g. `run_state.yaml`) those should be filtered.

- [ ] **Step 3: Add a filter if needed**

If noise exists, modify `apps/system/manifest.py`'s `build_skill_products_map`:

```python
# Paths to exclude from the regenerated-doc list (orchestration, not user-facing).
_EXCLUDE_PATHS = frozenset({"run_state.yaml", "inputs-manifest.yaml"})

def build_skill_products_map(entries: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for entry in entries:
        skill = entry.get("produced_by")
        path = entry.get("path")
        if not skill or not path or path in _EXCLUDE_PATHS:
            continue
        out.setdefault(skill, []).append(path)
    return out
```

Update the corresponding test in `apps/system/tests/test_manifest.py` to cover the exclusion.

- [ ] **Step 4: Commit (only if changes made)**

```bash
git add apps/system/manifest.py apps/system/tests/test_manifest.py
git commit -m "fix(system): exclude orchestration paths from skill-products map"
```

---

### Task F2: End-to-end smoke against a real opp

This task is manual + recorded; it isn't a runnable test. Pick a real opp folder with at least one completed Phase 1 run.

- [ ] **Step 1: Pick an opp**

Choose an opp with completed Phase 1 (e.g. one of the malaria opps). Note its slug and the current run-id.

- [ ] **Step 2: Run the flow end-to-end**

In the deployed UI (or local dev):
1. Open the opp's Phases view at the chosen run.
2. Expand the Phase 1 (design) decisions panel.
3. Edit one `idea-to-pdd`-sourced row (change the answer).
4. Edit one `pdd-to-work-order`-sourced row.
5. Confirm sticky bar shows "2 pending edits."
6. Click Fork & re-run.
7. Modal lists both `1-design/idea-to-pdd.md` and `1-design/pdd-to-work-order.gdoc`. Fork point default is `design`.
8. Submit. New run is created.
9. Open the new run's `decisions.yaml` in Drive. Confirm both edited rows show `status: overridden` with the new `default` values and the prior values in `options_considered`.
10. Trigger Phase 1 re-run in the new run (via whatever mechanism `/ace:run` uses today).
11. After re-run completes, open the new `1-design/idea-to-pdd.md` and `1-design/pdd-to-work-order.gdoc`. Confirm the regenerated prose reflects the edited answers.

- [ ] **Step 3: Document any surprises**

If anything diverged from the design (skill didn't honor `overridden`, edit dropped silently, etc.), capture in a learning under `docs/learnings/` and link from the spec.

- [ ] **Step 4: Run the regression probe**

```bash
LABS_TOKEN=... uv run --extra walkthrough python scripts/qa/labs_probe.py
```
Expected: no new failures on existing surfaces. (The probe doesn't cover the new editor; we add coverage in a follow-up.)

---

## Self-review (run after writing each task — verifications now)

### Spec coverage

Each item in `docs/specs/2026-05-22-questions-editor-design.md` → which task:

- Phases view, per-phase Questions panels → Task E4 (DecisionsPanel already integrated; we add edit props)
- Local-buffer edit pattern, coalesce, revert → Task C1 (reducer)
- Read-only when phase is running → **NOT YET COVERED** — needs a sub-step on D1 or E4. *Adding below.*
- Single save path = Fork with edits → Task E3 (dialog) + Task E4 (wire-up)
- Auto-fork-point = lowest edited ordinal → Task C3 (forkPoint helper)
- Manifest crosswalk → Task B1 + B2 (backend) + Task C2 (frontend hook)
- Save modal copy + flat list → Task E3
- Backend fork endpoint with `edits` payload → Tasks A1, A4, A5
- Status → overridden, options_considered preserves prior → Task A2
- Empty buffer → button disabled → Task E1 (bar renders null at count=0; button never shows)
- Concurrent edits / ETag → **OUT OF SCOPE for v1** per design ("last-write-wins for v1 if not reachable"); not adding task.
- Edited row's source not in manifest → Task C2 (falls back to empty list; modal renders fallback line) ✓
- Editing an already-`overridden` row → Task A2 (test covers this) ✓
- gdoc round-trip stays running → no code change needed; out-of-scope verified ✓

### Adding the missing read-only-when-running gate

The spec calls for editing to be disabled while a phase is `running`. This needs to be in the PhaseView wire-up. Adding to Task E4:

> **Task E4 step 2 addendum**: When passing edit props to `DecisionsPanel`, gate them on the phase status. If `snapshot.current_run.phases[<phase>].status === "running"`, do NOT pass `editBuffer`/`onEdit`/`onRevert` — the panel reverts to read-only mode automatically. Add a small `<div className="text-xs text-muted-foreground">Editing locked while phase is running</div>` near the panel when in this state. (This is a small change to the wire-up, not a new task.)

### Placeholder scan

Reviewed all code blocks — every TDD step shows real code. Two test files (`test_api_fork.py`, `test_api_skill_products.py`) reference the existing project workspace-fixture pattern without naming the exact fixture — added a NOTE inline directing the implementer to `apps/opps/tests/conftest.py`. Acceptable: the writing-plans skill allows referencing existing project conventions when calling them out explicitly.

### Type consistency

- `EditOp` shape `{row_id, new_answer}` used identically in backend (`OppForkEditIn`), reducer (`EditOp`), API client (`ForkOppBody.edits[]`), and dialog props.
- `Decision.default` (the answer) used consistently across `EditableDecisionRow`, `computeAffectedDocs`, `computeForkPoint`.
- `PhaseInfo.name`/`ordinal` used consistently in `computeForkPoint` and the dialog dropdown.
- Skill products map keyed by `decision.source` (not `decision.skill`) — these can differ; `source` is the skill that *raised* the question, which is the right key for "what gets regenerated."

No naming inconsistencies found.

---

## Notes for the executing agent

- The forker module (`apps/opps/opp_forker.py`) is 569 lines but only ~3 small changes here. Keep the file structure intact.
- The frontend `DecisionsPanel.tsx` is read-only today. Don't fork it into a new file — extend it. The 6 new tests verify backwards-compat with the read-only path.
- Fork → re-run is not wired in this plan: forking creates the new run folder, but kicking off the actual Phase 1 re-run uses whatever `/ace:run` mechanism exists today. After Task E3 navigates to the new run, the user clicks the existing "Run phase" button to start it (or whatever the existing affordance is). If the existing UI doesn't have such a button, that's a separate plan.
- The user has not used the gdoc round-trip; assume it works in the background and don't touch `decisions-render` / `decisions-sync`.
