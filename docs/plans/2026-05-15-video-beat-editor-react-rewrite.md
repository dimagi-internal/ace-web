# Video Beat Editor — React Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the iframe-served HTML clip-explorer editor with a native React surface that uses a local-buffer dirty-state model, a swappable side-drawer (modal-ready) for click-to-edit, batched save via a new `/edit-batch` endpoint, and a fixed trim widget. Stats (`problem`, `impact[]`) become editable; clips and narration carry over.

**Architecture:** Outer `VideoExplorerPage` keeps its header + Re-render button. Iframe contents are replaced by `<BeatEditor>`, a context-driven tree whose reducer owns an append-with-coalescing buffer of `PendingChange`s. Beat cards read from a memoized `effectiveSpec = applyOps(spec, buffer)`. Edits open `<EditDrawer>` (DrawerShell-or-ModalShell) hosting kind-switched `<EditPanel>`s. Top-level Save POSTs the buffer to `POST /edit-batch`, which loads/mutates/saves YAML once.

**Tech Stack:** Django Ninja v1 + Pydantic v2 + ruamel.yaml (backend); React 19 + TypeScript + vitest + React Testing Library (frontend); existing `serve_media` endpoint for clip MP4s.

**Spec:** `docs/specs/2026-05-15-video-beat-editor-react-port-design.md`

---

## File map

### Backend — `apps/videos/`

- Modify `apps/videos/schemas.py` — add `StatEditIn`, `EditBatchIn`, `EditBatchOut`, extend `ClipEditIn.op` literal with `"set-stat"`
- Modify `apps/videos/service.py` — extract `_apply_single_op(doc, op) -> EditResult`, add `apply_edit_batch(...)`, add `set-stat` handler
- Modify `apps/videos/api.py` — add `POST /edit-batch` route
- Create `apps/videos/tests/test_set_stat.py`
- Create `apps/videos/tests/test_edit_batch.py`

### Frontend — `frontend/src/`

Editor tree (all new under `frontend/src/components/videos/`):

```
components/videos/
├── types.ts                          PendingChange, EditorState, WidgetRef
├── applyOps.ts                       Pure spec mutator
├── editorReducer.ts                  Pure reducer (coalescing)
├── BeatEditorContext.tsx             Context + Provider + hook
├── BeatEditor.tsx                    Top-level component
├── BeatEditorTopBar.tsx              Dirty count + Save + Discard
├── TimelineStrip.tsx                 Colored beat segments
├── FinalVideoPlayer.tsx              <video> for output.mp4
├── BeatList.tsx                      Iterates beats
├── BeatCard.tsx                      One beat — header + widgets
├── widgets/
│   ├── ClipSlotWidget.tsx
│   ├── NarrationWidget.tsx
│   ├── StatsWidget.tsx
│   └── BrandTemplateWidget.tsx
└── drawer/
    ├── EditDrawer.tsx                Mode switcher
    ├── DrawerShell.tsx               Right-sliding sheet
    ├── ModalShell.tsx                Centered overlay
    ├── TrimBar.tsx                   Reusable trim slider
    └── panels/
        ├── ClipTrimPanel.tsx
        ├── NarrationPanel.tsx
        └── StatPanel.tsx
```

Tests (colocated, `__tests__/` subdirectory):

```
components/videos/__tests__/
├── applyOps.test.ts
├── editorReducer.test.ts
├── TrimBar.test.tsx
├── NarrationPanel.test.tsx
├── StatPanel.test.tsx
└── BeatEditor.test.tsx
```

Other frontend changes:

- Modify `frontend/src/api/videos.ts` — add `EditBatchOp`, `EditBatchResult`, `submitEditBatch()`, `getProgramSpec()`
- Modify `frontend/src/pages/VideoExplorerPage.tsx` — gate iframe vs `<BeatEditor>` behind `FEATURE_BEAT_EDITOR_REACT`
- Modify `config/settings/base.py` — add `ACE_VIDEO_BEAT_EDITOR_REACT` feature flag (Django setting; exposed to frontend via existing settings-injection)

---

## Phase A — Backend

### Task 1: Pydantic schemas for set-stat and batch

**Files:**
- Modify: `apps/videos/schemas.py`

- [ ] **Step 1: Extend `ClipEditIn.op` and add new schemas**

Replace the existing `ClipEditIn` block (around `apps/videos/schemas.py:98-112`) with:

```python
class ClipEditIn(StrictModel):
    op: Literal[
        "set-clip-start",
        "set-clip-trim",
        "set-clip-asset",
        "set-narration",
        "set-stat",
    ]
    # set-clip-*
    kind: Literal["scene-clip", "product-beat"] | None = None
    index: int | None = None
    start_seconds: float | None = None
    duration_seconds: float | None = None
    alias: str | None = None
    # set-narration
    beatId: str | None = None
    text: str | None = None
    # set-stat
    path: str | None = None        # "problem" | "impact[N]"
    big: str | None = None
    caption: str | None = None
    source: str | None = None      # explicit "" clears; absence is no-op


class ClipEditOut(StrictModel):
    ok: bool
    message: str
    rerender_triggered: bool


class EditBatchIn(StrictModel):
    ops: list[ClipEditIn] = Field(min_length=1, max_length=200)


class EditBatchOut(StrictModel):
    ok: bool
    applied: int
    message: str
```

The `Field` import is already in the module (line 13). Confirm.

- [ ] **Step 2: Confirm the file still parses**

Run: `python -c "from apps.videos import schemas; print(schemas.EditBatchIn)"`
Expected: `<class 'apps.videos.schemas.EditBatchIn'>`

- [ ] **Step 3: Commit**

```bash
git add apps/videos/schemas.py
git commit -m "videos(schemas): add set-stat op + EditBatchIn/Out for batched edits"
```

---

### Task 2: Refactor `apply_edit` into `_apply_single_op`

The goal is to make the per-op mutation pure (operates on an in-memory ruamel doc) so the batch wrapper can reuse it.

**Files:**
- Modify: `apps/videos/service.py`

- [ ] **Step 1: Write a failing test for the refactored shape**

Create test in `apps/videos/tests/test_service.py` (append to end of file):

```python
def test_apply_single_op_returns_result_without_saving(monkeypatch):
    from apps.videos import service
    from ruamel.yaml import YAML
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    from io import StringIO

    doc = yaml.load(StringIO("""\
scene:
  clips:
    - "@alpha"
narration:
  by_beat: {}
"""))
    result = service._apply_single_op(doc, {
        "op": "set-narration", "beatId": "hook", "text": "Hello"
    })
    assert result.ok
    assert doc["narration"]["by_beat"]["hook"] == "Hello"
```

- [ ] **Step 2: Run test (expect import error / NameError)**

Run: `pytest apps/videos/tests/test_service.py::test_apply_single_op_returns_result_without_saving -v`
Expected: FAIL with `AttributeError: module 'apps.videos.service' has no attribute '_apply_single_op'`

- [ ] **Step 3: Refactor `apply_edit` in `apps/videos/service.py`**

Replace the existing `apply_edit` function (currently around `apps/videos/service.py:404-495`) with:

```python
def _apply_single_op(doc: Any, op: dict[str, Any]) -> EditResult:
    """Apply one edit op to an in-memory ruamel YAML doc. Pure mutation,
    no I/O. Returns ok=False on validation failure (caller decides whether
    to abort the whole batch)."""
    name = op.get("op")

    if name in {"set-clip-start", "set-clip-trim", "set-clip-asset"}:
        index = op.get("index")
        kind = op.get("kind")
        if not isinstance(index, int):
            return EditResult(False, "index must be an integer")
        keys = _clip_path_keys(kind, index)
        node = _get_in(doc, keys)

        if name == "set-clip-start":
            start_seconds = op.get("start_seconds")
            if not isinstance(start_seconds, (int, float)):
                return EditResult(False, "start_seconds must be a number")
            if isinstance(node, str):
                _set_in(doc, keys, {"asset": node, "start_seconds": float(start_seconds)})
            elif isinstance(node, dict):
                node["start_seconds"] = float(start_seconds)
            else:
                return EditResult(False, f"Could not find {kind}[{index}]")
            return EditResult(True, f"Set {kind}[{index}].start_seconds = {start_seconds}")

        if name == "set-clip-trim":
            start_seconds = op.get("start_seconds")
            duration_seconds = op.get("duration_seconds")
            if not isinstance(start_seconds, (int, float)):
                return EditResult(False, "start_seconds must be a number")
            if not isinstance(duration_seconds, (int, float)):
                return EditResult(False, "duration_seconds must be a number")
            if isinstance(node, str):
                _set_in(doc, keys, {
                    "asset": node,
                    "start_seconds": float(start_seconds),
                    "duration_seconds": float(duration_seconds),
                })
            elif isinstance(node, dict):
                node["start_seconds"] = float(start_seconds)
                node["duration_seconds"] = float(duration_seconds)
            else:
                return EditResult(False, f"Could not find {kind}[{index}]")
            return EditResult(True, f"Set {kind}[{index}] trim window")

        if name == "set-clip-asset":
            alias = op.get("alias")
            if not isinstance(alias, str) or not alias:
                return EditResult(False, "alias must be a non-empty string")
            new_ref = f"@{alias}"
            if isinstance(node, str):
                if kind == "scene-clip":
                    _set_in(doc, keys, new_ref)
                else:
                    _set_in(doc, keys, {"asset": new_ref})
            elif isinstance(node, dict):
                node["asset"] = new_ref
            else:
                return EditResult(False, f"Could not find {kind}[{index}]")
            return EditResult(True, f"Swapped {kind}[{index}] -> @{alias}")

    if name == "set-narration":
        beat_id = op.get("beatId")
        text = op.get("text")
        if not isinstance(beat_id, str) or not beat_id:
            return EditResult(False, "beatId must be a non-empty string")
        if not isinstance(text, str):
            return EditResult(False, "text must be a string")
        narration = doc.setdefault("narration", {})
        by_beat = narration.setdefault("by_beat", {})
        by_beat[beat_id] = text
        return EditResult(True, f"Updated narration.by_beat.{beat_id}")

    if name == "set-stat":
        # Stub for Task 3 — fails for now so the test stays red until then.
        return EditResult(False, "set-stat not yet implemented")

    return EditResult(False, f"Unknown op: {name!r}")


def apply_edit(workspace: Workspace, slug: str, run_id: str, body: dict[str, Any]) -> EditResult:
    """Single-op edit — load, apply one op, save. Backward compat wrapper
    around `_apply_single_op`. Used by the existing `POST /edit` endpoint."""
    layout, client = layout_for(workspace)
    spec_yaml = drive.read_spec(layout, client, slug, run_id)
    if spec_yaml is None:
        return EditResult(False, f"Spec not found for {slug}/{run_id}")
    y = _yaml()
    doc = y.load(spec_yaml)
    result = _apply_single_op(doc, body)
    if not result.ok:
        return result
    new_yaml = _dump_yaml(doc)
    drive.write_spec(layout, client, slug, run_id, new_yaml)
    cache.set_spec(workspace.slug, slug, run_id, new_yaml)
    return result
```

- [ ] **Step 4: Run the new test plus existing edit tests**

Run: `pytest apps/videos/tests/test_service.py apps/videos/tests/test_api.py::test_post_edit_saves_spec_without_triggering_render -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add apps/videos/service.py apps/videos/tests/test_service.py
git commit -m "videos(service): extract _apply_single_op for batch reuse"
```

---

### Task 3: `set-stat` op handler

**Files:**
- Modify: `apps/videos/service.py`
- Create: `apps/videos/tests/test_set_stat.py`

- [ ] **Step 1: Write failing tests**

Create `apps/videos/tests/test_set_stat.py`:

```python
"""Tests for the set-stat edit op (problem.* and impact[N].*)."""
from io import StringIO

import pytest
from ruamel.yaml import YAML

from apps.videos import service


def _doc(yaml_text: str):
    y = YAML(typ="rt")
    y.preserve_quotes = True
    return y.load(StringIO(yaml_text))


def test_set_stat_updates_problem_fields():
    doc = _doc("""\
problem:
  big: "29%"
  caption: "old caption"
  source: "NDHS 2018"
""")
    r = service._apply_single_op(doc, {
        "op": "set-stat", "path": "problem",
        "big": "31%", "caption": "new caption",
    })
    assert r.ok, r.message
    assert doc["problem"]["big"] == "31%"
    assert doc["problem"]["caption"] == "new caption"
    assert doc["problem"]["source"] == "NDHS 2018"   # untouched


def test_set_stat_clears_source_when_explicit_empty_string():
    doc = _doc("""\
problem:
  big: "29%"
  caption: "x"
  source: "NDHS 2018"
""")
    r = service._apply_single_op(doc, {
        "op": "set-stat", "path": "problem", "source": "",
    })
    assert r.ok
    assert "source" not in doc["problem"]


def test_set_stat_updates_impact_item_by_index():
    doc = _doc("""\
impact:
  - big: "$320K"
    caption: "grant"
  - big: "2,000"
    caption: "pairs"
""")
    r = service._apply_single_op(doc, {
        "op": "set-stat", "path": "impact[1]",
        "big": "2,500", "caption": "pairs in cohort",
    })
    assert r.ok
    assert doc["impact"][0]["big"] == "$320K"     # untouched
    assert doc["impact"][1]["big"] == "2,500"
    assert doc["impact"][1]["caption"] == "pairs in cohort"


def test_set_stat_rejects_unknown_path():
    doc = _doc("problem: {big: x, caption: y}\n")
    r = service._apply_single_op(doc, {
        "op": "set-stat", "path": "nope", "big": "z",
    })
    assert not r.ok
    assert "path" in r.message.lower()


def test_set_stat_rejects_impact_index_out_of_range():
    doc = _doc("""\
impact:
  - big: "a"
    caption: "b"
""")
    r = service._apply_single_op(doc, {
        "op": "set-stat", "path": "impact[5]", "big": "x",
    })
    assert not r.ok
    assert "range" in r.message.lower() or "index" in r.message.lower()
```

- [ ] **Step 2: Run tests (expect 5 failures from the stub)**

Run: `pytest apps/videos/tests/test_set_stat.py -v`
Expected: 5 FAIL ("set-stat not yet implemented")

- [ ] **Step 3: Implement `set-stat`**

In `apps/videos/service.py`, replace the `set-stat` stub block inside `_apply_single_op` with:

```python
    if name == "set-stat":
        import re
        path = op.get("path")
        if not isinstance(path, str):
            return EditResult(False, "path must be a string")

        if path == "problem":
            node = doc.get("problem")
            if not isinstance(node, dict):
                return EditResult(False, "spec has no `problem` section")
        else:
            m = re.fullmatch(r"impact\[(\d+)\]", path)
            if not m:
                return EditResult(False, f"unknown path {path!r}; expected 'problem' or 'impact[N]'")
            idx = int(m.group(1))
            impact = doc.get("impact")
            if not isinstance(impact, list):
                return EditResult(False, "spec has no `impact` section")
            if idx < 0 or idx >= len(impact):
                return EditResult(False, f"impact index {idx} out of range (len={len(impact)})")
            node = impact[idx]
            if not isinstance(node, dict):
                return EditResult(False, f"impact[{idx}] is not a mapping")

        for field in ("big", "caption"):
            val = op.get(field)
            if val is None:
                continue  # field absent → no change
            if not isinstance(val, str):
                return EditResult(False, f"{field} must be a string")
            node[field] = val

        # `source` has tri-state semantics: absent → no change, "" → clear, str → set
        if "source" in op:
            val = op["source"]
            if val is None or val == "":
                node.pop("source", None)
            elif isinstance(val, str):
                node["source"] = val
            else:
                return EditResult(False, "source must be a string")

        return EditResult(True, f"Updated stat {path}")
```

- [ ] **Step 4: Run tests**

Run: `pytest apps/videos/tests/test_set_stat.py -v`
Expected: all 5 PASS

- [ ] **Step 5: Commit**

```bash
git add apps/videos/service.py apps/videos/tests/test_set_stat.py
git commit -m "videos(service): add set-stat op (problem.* and impact[N].*)"
```

---

### Task 4: `apply_edit_batch` wrapper

**Files:**
- Modify: `apps/videos/service.py`
- Create: `apps/videos/tests/test_edit_batch.py`

- [ ] **Step 1: Write failing tests**

Create `apps/videos/tests/test_edit_batch.py`:

```python
"""Tests for service.apply_edit_batch — single load-mutate-save round trip."""
import pytest
from unittest import mock

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive, service
from apps.workspaces.models import Workspace, WorkspaceMembership
from django.contrib.auth import get_user_model

User = get_user_model()


SPEC = """\
slug: demo
workspace: ws1
name: Demo
manifest:
  alpha: gdrive:abc.mp4
scene:
  clips:
    - "@alpha"
product:
  beats:
    - asset: "@alpha"
      caption: "first"
problem:
  big: "29%"
  caption: "old"
impact:
  - big: "$1"
    caption: "a"
  - big: "$2"
    caption: "b"
narration:
  by_beat: {}
"""


@pytest.fixture
def ws_and_drive(db, monkeypatch, tmp_path, settings):
    settings.ACE_VIDEOS_ROOT = str(tmp_path / "videos-scratch")
    user = User.objects.create_user(email="alice@example.com")
    ws = Workspace.objects.create(slug="ws1", name="Ws1", drive_root_folder_id="ws1-root")
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="owner")
    client = FakeDriveClient.from_tree({"ws1-root": {}})
    monkeypatch.setattr(drive, "client_for_workspace", lambda w: client)
    # Seed videos/programs/demo/runs/run-001/spec.yaml
    videos_id = client.create_folder("ws1-root", "videos")
    programs_id = client.create_folder(videos_id, "programs")
    demo_id = client.create_folder(programs_id, "demo")
    runs_id = client.create_folder(demo_id, "runs")
    run_id = client.create_folder(runs_id, "run-001")
    client.create_file(run_id, "spec.yaml", SPEC.encode())
    return ws, client


def test_apply_edit_batch_applies_all_ops_in_order(ws_and_drive):
    ws, fake = ws_and_drive
    result = service.apply_edit_batch(ws, "demo", "run-001", [
        {"op": "set-narration", "beatId": "hook", "text": "Hi"},
        {"op": "set-stat", "path": "problem", "big": "31%"},
        {"op": "set-stat", "path": "impact[1]", "big": "$5"},
    ])
    assert result.ok
    assert result.applied == 3
    # Verify YAML round-tripped to Drive with all three ops applied.
    saved = drive.read_spec(*service.layout_for(ws), "demo", "run-001")
    assert "Hi" in saved
    assert "31%" in saved
    assert "$5" in saved


def test_apply_edit_batch_is_all_or_nothing_on_invalid_op(ws_and_drive):
    ws, _ = ws_and_drive
    result = service.apply_edit_batch(ws, "demo", "run-001", [
        {"op": "set-narration", "beatId": "hook", "text": "Hi"},
        {"op": "set-stat", "path": "impact[99]", "big": "boom"},
    ])
    assert not result.ok
    assert result.applied == 0
    # Original spec untouched (no "Hi" persisted).
    saved = drive.read_spec(*service.layout_for(ws), "demo", "run-001")
    assert "Hi" not in saved


def test_apply_edit_batch_preserves_comments(ws_and_drive, monkeypatch):
    ws, fake = ws_and_drive
    # Overwrite spec with comment-bearing yaml
    yaml_with_comments = """\
# A comment above the field
problem:
  big: "29%"        # inline comment
  caption: "x"
"""
    monkeypatch.setattr(
        drive, "read_spec",
        lambda *a, **kw: yaml_with_comments,
    )
    writes: list[str] = []
    monkeypatch.setattr(
        drive, "write_spec",
        lambda layout, client, slug, run, content: writes.append(content),
    )
    result = service.apply_edit_batch(ws, "demo", "run-001", [
        {"op": "set-stat", "path": "problem", "big": "33%"},
    ])
    assert result.ok
    assert writes, "expected one drive.write_spec call"
    saved = writes[0]
    assert "# A comment above the field" in saved
    assert "# inline comment" in saved
    assert "33%" in saved
```

- [ ] **Step 2: Run tests (expect 3 fails — `apply_edit_batch` undefined)**

Run: `pytest apps/videos/tests/test_edit_batch.py -v`
Expected: 3 FAIL with `AttributeError`

- [ ] **Step 3: Implement `apply_edit_batch`**

Append to `apps/videos/service.py` (after `apply_edit`):

```python
@dataclass(frozen=True)
class BatchResult:
    ok: bool
    applied: int
    message: str


def apply_edit_batch(
    workspace: Workspace,
    slug: str,
    run_id: str,
    ops: list[dict[str, Any]],
) -> BatchResult:
    """Apply N edit ops to spec.yaml in one Drive round-trip. All-or-nothing:
    if any op fails validation, the doc is not saved and `applied=0`."""
    if not ops:
        return BatchResult(True, 0, "no-op (empty batch)")

    layout, client = layout_for(workspace)
    spec_yaml = drive.read_spec(layout, client, slug, run_id)
    if spec_yaml is None:
        return BatchResult(False, 0, f"Spec not found for {slug}/{run_id}")

    y = _yaml()
    doc = y.load(spec_yaml)
    messages: list[str] = []
    for i, op in enumerate(ops):
        result = _apply_single_op(doc, op)
        if not result.ok:
            return BatchResult(False, 0, f"op[{i}] failed: {result.message}")
        messages.append(result.message)

    new_yaml = _dump_yaml(doc)
    drive.write_spec(layout, client, slug, run_id, new_yaml)
    cache.set_spec(workspace.slug, slug, run_id, new_yaml)
    return BatchResult(True, len(ops), "; ".join(messages))
```

- [ ] **Step 4: Run tests**

Run: `pytest apps/videos/tests/test_edit_batch.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add apps/videos/service.py apps/videos/tests/test_edit_batch.py
git commit -m "videos(service): apply_edit_batch for one-Drive-round-trip batch saves"
```

---

### Task 5: `POST /edit-batch` endpoint

**Files:**
- Modify: `apps/videos/api.py`
- Modify: `apps/videos/tests/test_api.py`

- [ ] **Step 1: Write failing API test**

Append to `apps/videos/tests/test_api.py` (after `test_post_edit_saves_spec_without_triggering_render`):

```python
@pytest.mark.django_db
def test_post_edit_batch_applies_multiple_ops(member_client, videos_root, fake_drive):
    client, _ = member_client
    with mock.patch("apps.videos.service.subprocess.Popen") as popen:
        resp = client.post(
            "/api/w/ws1/videos/programs/demo/runs/run-001/edit-batch",
            data={"ops": [
                {"op": "set-narration", "beatId": "intro", "text": "Hello"},
                {"op": "set-clip-trim", "kind": "scene-clip", "index": 0,
                 "start_seconds": 1.0, "duration_seconds": 3.0},
            ]},
            content_type="application/json",
        )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["ok"] is True
    assert body["applied"] == 2
    assert popen.call_count == 0  # save only


@pytest.mark.django_db
def test_post_edit_batch_400_on_invalid_op(member_client, videos_root, fake_drive):
    client, _ = member_client
    resp = client.post(
        "/api/w/ws1/videos/programs/demo/runs/run-001/edit-batch",
        data={"ops": [
            {"op": "set-narration", "beatId": "intro", "text": "Hello"},
            {"op": "set-stat", "path": "nope"},
        ]},
        content_type="application/json",
    )
    assert resp.status_code == 400, resp.content


@pytest.mark.django_db
def test_post_edit_batch_400_on_empty_ops(member_client, videos_root, fake_drive):
    client, _ = member_client
    resp = client.post(
        "/api/w/ws1/videos/programs/demo/runs/run-001/edit-batch",
        data={"ops": []},
        content_type="application/json",
    )
    assert resp.status_code == 422  # Ninja validation — min_length=1
```

- [ ] **Step 2: Run tests (expect 404 / route-missing)**

Run: `pytest apps/videos/tests/test_api.py::test_post_edit_batch_applies_multiple_ops -v`
Expected: FAIL (404 or similar)

- [ ] **Step 3: Add the route**

In `apps/videos/api.py`, immediately after the `post_edit` function (around line 416), add:

```python
@router.post(
    "/programs/{program_slug}/runs/{run_id}/edit-batch",
    response=EditBatchOut,
    summary="Save N edits to spec.yaml in one Drive round-trip (save only — does NOT render)",
)
def post_edit_batch(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
    run_id: Annotated[str, PathParam()],
    body: EditBatchIn,
) -> EditBatchOut:
    """Atomic batch edit. All ops are validated and applied in order;
    if any fails, the spec is not saved (all-or-nothing).
    """
    workspace = resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace, program_slug, run_id)
    ops = [op.model_dump(exclude_none=True) for op in body.ops]
    result = service.apply_edit_batch(workspace, program_slug, run_id, ops)
    if not result.ok:
        raise ProblemError(
            400,
            "Edit batch could not be applied",
            type_=TYPE_VALIDATION,
            detail=result.message,
        )
    return EditBatchOut(
        ok=True,
        applied=result.applied,
        message=result.message + " — click Re-render to regenerate.",
    )
```

Also update the imports near `apps/videos/api.py:30` if missing:

```python
from apps.videos.schemas import (
    # ...existing imports...
    EditBatchIn,
    EditBatchOut,
)
```

- [ ] **Step 4: Run tests**

Run: `pytest apps/videos/tests/test_api.py -k "edit_batch or post_edit" -v`
Expected: all PASS (existing `/edit` tests still pass, three new batch tests pass)

- [ ] **Step 5: Commit**

```bash
git add apps/videos/api.py apps/videos/tests/test_api.py
git commit -m "videos(api): POST /edit-batch endpoint"
```

---

## Phase B — Frontend pure logic (no UI yet)

### Task 6: `types.ts` and `applyOps.ts`

**Files:**
- Create: `frontend/src/components/videos/types.ts`
- Create: `frontend/src/components/videos/applyOps.ts`
- Create: `frontend/src/components/videos/__tests__/applyOps.test.ts`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/videos/__tests__/applyOps.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { ProgramSpec, PendingChange } from "../types";
import { applyOps } from "../applyOps";

const baseSpec: ProgramSpec = {
  slug: "demo",
  name: "Demo",
  scene: { clips: ["@alpha"] },
  product: { beats: [{ asset: "@alpha", caption: "first" }] },
  problem: { big: "29%", caption: "old", source: "NDHS 2018" },
  impact: [
    { big: "$1", caption: "a" },
    { big: "$2", caption: "b" },
  ],
  narration: { by_beat: {} },
};

describe("applyOps", () => {
  it("returns spec unchanged for empty ops", () => {
    expect(applyOps(baseSpec, [])).toEqual(baseSpec);
  });

  it("applies set-narration", () => {
    const ops: PendingChange[] = [
      { op: "set-narration", beatId: "hook", text: "Hi" },
    ];
    const out = applyOps(baseSpec, ops);
    expect(out.narration.by_beat.hook).toBe("Hi");
    expect(baseSpec.narration.by_beat).toEqual({}); // immutability
  });

  it("applies set-stat for problem", () => {
    const ops: PendingChange[] = [
      { op: "set-stat", path: "problem", big: "31%" },
    ];
    const out = applyOps(baseSpec, ops);
    expect(out.problem?.big).toBe("31%");
    expect(out.problem?.caption).toBe("old"); // untouched
  });

  it("applies set-stat for impact[i]", () => {
    const ops: PendingChange[] = [
      { op: "set-stat", path: "impact[1]", big: "$5" },
    ];
    const out = applyOps(baseSpec, ops);
    expect(out.impact?.[0].big).toBe("$1");
    expect(out.impact?.[1].big).toBe("$5");
  });

  it("applies set-clip-trim to product beat", () => {
    const ops: PendingChange[] = [
      { op: "set-clip-trim", kind: "product-beat", index: 0,
        start_seconds: 1.5, duration_seconds: 3.0 },
    ];
    const out = applyOps(baseSpec, ops);
    expect(out.product?.beats[0]).toMatchObject({
      asset: "@alpha", start_seconds: 1.5, duration_seconds: 3.0,
    });
  });

  it("applies set-clip-asset to scene clip (replaces string ref)", () => {
    const ops: PendingChange[] = [
      { op: "set-clip-asset", kind: "scene-clip", index: 0, alias: "beta" },
    ];
    const out = applyOps(baseSpec, ops);
    expect(out.scene?.clips[0]).toBe("@beta");
  });

  it("applies multiple ops in order", () => {
    const ops: PendingChange[] = [
      { op: "set-narration", beatId: "hook", text: "v1" },
      { op: "set-narration", beatId: "hook", text: "v2" },
      { op: "set-stat", path: "problem", big: "31%" },
    ];
    const out = applyOps(baseSpec, ops);
    expect(out.narration.by_beat.hook).toBe("v2"); // last wins
    expect(out.problem?.big).toBe("31%");
  });
});
```

- [ ] **Step 2: Run tests (expect import error)**

Run: `bun run test -- src/components/videos/__tests__/applyOps.test.ts`
Expected: FAIL — cannot resolve `../applyOps` and `../types`

- [ ] **Step 3: Implement `types.ts`**

Create `frontend/src/components/videos/types.ts`:

```ts
// Shape of the parsed spec.yaml as the editor sees it. Mirrors the
// backend's ruamel doc structure but as TypeScript types. Only fields
// the editor reads are typed here — pass-through for anything else.
export interface ProgramSpec {
  slug: string;
  name: string;
  tagline?: string | null;
  scene?: { clips: (string | ClipObject)[] };
  product?: { beats: (string | ClipObject)[] };
  problem?: Stat;
  impact?: Stat[];
  narration: { by_beat: Record<string, string>; generator?: string };
  manifest?: Record<string, string>;
  beats?: { id: string; kind: string; seconds: number }[];
  voice?: { provider?: string; voice_id?: string; model?: string };
  music_bed?: Record<string, unknown>;
  // unknown extra fields preserved by ruamel; we don't model them
  [extra: string]: unknown;
}

export interface ClipObject {
  asset: string;
  start_seconds?: number;
  duration_seconds?: number;
  caption?: string;
}

export interface Stat {
  big: string;
  caption: string;
  source?: string;
}

// One pending edit. Mirrors backend ops + the coalescing key per op kind.
export type PendingChange =
  | { op: "set-clip-trim"; kind: "scene-clip" | "product-beat"; index: number;
      start_seconds: number; duration_seconds: number }
  | { op: "set-clip-asset"; kind: "scene-clip" | "product-beat"; index: number; alias: string }
  | { op: "set-narration"; beatId: string; text: string }
  | { op: "set-stat"; path: string; big?: string; caption?: string; source?: string };

// What the drawer is currently editing.
export type WidgetRef =
  | { kind: "clip-trim"; clipKind: "scene-clip" | "product-beat"; beatId: string; index: number }
  | { kind: "narration"; beatId: string }
  | { kind: "stat"; beatId: string; path: string };

export interface EditorState {
  spec: ProgramSpec;
  buffer: PendingChange[];
  drawerTarget: WidgetRef | null;
  saveState:
    | { status: "idle" }
    | { status: "saving" }
    | { status: "saved"; at: number }
    | { status: "error"; message: string };
}

// Coalescing key — two ops with the same key collapse to the later one.
export function opCoalesceKey(op: PendingChange): string {
  switch (op.op) {
    case "set-clip-trim":
    case "set-clip-asset":
      return `${op.op}:${op.kind}:${op.index}`;
    case "set-narration":
      return `set-narration:${op.beatId}`;
    case "set-stat":
      return `set-stat:${op.path}`;
  }
}
```

- [ ] **Step 4: Implement `applyOps.ts`**

Create `frontend/src/components/videos/applyOps.ts`:

```ts
import type { ProgramSpec, PendingChange, ClipObject } from "./types";

// Pure function: returns a NEW spec with ops applied in order. Does not
// mutate input. Structural sharing where possible; deep-clones only the
// branches that change.
export function applyOps(spec: ProgramSpec, ops: PendingChange[]): ProgramSpec {
  if (ops.length === 0) return spec;
  // Deep clone via JSON to keep this simple — specs are small (~KB).
  // If profiling shows hot path, swap to structuredClone or immer.
  const out: ProgramSpec = JSON.parse(JSON.stringify(spec));
  for (const op of ops) applyOne(out, op);
  return out;
}

function applyOne(spec: ProgramSpec, op: PendingChange): void {
  switch (op.op) {
    case "set-narration": {
      spec.narration ??= { by_beat: {} };
      spec.narration.by_beat ??= {};
      spec.narration.by_beat[op.beatId] = op.text;
      return;
    }
    case "set-clip-trim": {
      const slot = getClipSlot(spec, op.kind, op.index);
      if (!slot) return;
      const obj = ensureClipObject(spec, op.kind, op.index, slot);
      obj.start_seconds = op.start_seconds;
      obj.duration_seconds = op.duration_seconds;
      return;
    }
    case "set-clip-asset": {
      const slot = getClipSlot(spec, op.kind, op.index);
      if (!slot) return;
      const newRef = `@${op.alias}`;
      if (typeof slot === "string") {
        if (op.kind === "scene-clip") {
          spec.scene!.clips[op.index] = newRef;
        } else {
          spec.product!.beats[op.index] = { asset: newRef };
        }
      } else {
        slot.asset = newRef;
      }
      return;
    }
    case "set-stat": {
      const node = resolveStatNode(spec, op.path);
      if (!node) return;
      if (op.big !== undefined) node.big = op.big;
      if (op.caption !== undefined) node.caption = op.caption;
      if (op.source !== undefined) {
        if (op.source === "") delete node.source;
        else node.source = op.source;
      }
      return;
    }
  }
}

function getClipSlot(spec: ProgramSpec, kind: "scene-clip" | "product-beat", index: number):
  string | ClipObject | null
{
  if (kind === "scene-clip") return spec.scene?.clips[index] ?? null;
  return spec.product?.beats[index] ?? null;
}

function ensureClipObject(
  spec: ProgramSpec,
  kind: "scene-clip" | "product-beat",
  index: number,
  current: string | ClipObject,
): ClipObject {
  if (typeof current === "object") return current;
  const obj: ClipObject = { asset: current };
  if (kind === "scene-clip") spec.scene!.clips[index] = obj;
  else spec.product!.beats[index] = obj;
  return obj;
}

function resolveStatNode(spec: ProgramSpec, path: string): { big: string; caption: string; source?: string } | null {
  if (path === "problem") return spec.problem ?? null;
  const m = /^impact\[(\d+)\]$/.exec(path);
  if (!m) return null;
  const i = parseInt(m[1], 10);
  return spec.impact?.[i] ?? null;
}
```

- [ ] **Step 5: Run tests**

Run: `bun run test -- src/components/videos/__tests__/applyOps.test.ts`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/videos/types.ts \
        frontend/src/components/videos/applyOps.ts \
        frontend/src/components/videos/__tests__/applyOps.test.ts
git commit -m "videos(editor): pure types + applyOps spec mutator with tests"
```

---

### Task 7: `editorReducer.ts` with coalescing

**Files:**
- Create: `frontend/src/components/videos/editorReducer.ts`
- Create: `frontend/src/components/videos/__tests__/editorReducer.test.ts`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/videos/__tests__/editorReducer.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { EditorState, PendingChange, ProgramSpec, WidgetRef } from "../types";
import { editorReducer, initialEditorState } from "../editorReducer";

const spec: ProgramSpec = {
  slug: "demo", name: "Demo",
  narration: { by_beat: {} },
};

function fresh(): EditorState {
  return initialEditorState(spec);
}

describe("editorReducer", () => {
  it("initial state has empty buffer + idle save", () => {
    const s = fresh();
    expect(s.buffer).toEqual([]);
    expect(s.saveState.status).toBe("idle");
    expect(s.drawerTarget).toBeNull();
  });

  it("OPEN_DRAWER sets target", () => {
    const target: WidgetRef = { kind: "narration", beatId: "hook" };
    const s = editorReducer(fresh(), { type: "OPEN_DRAWER", target });
    expect(s.drawerTarget).toEqual(target);
  });

  it("CLOSE_DRAWER clears target", () => {
    const target: WidgetRef = { kind: "narration", beatId: "hook" };
    let s = editorReducer(fresh(), { type: "OPEN_DRAWER", target });
    s = editorReducer(s, { type: "CLOSE_DRAWER" });
    expect(s.drawerTarget).toBeNull();
  });

  it("APPEND_OP appends a new op", () => {
    const op: PendingChange = { op: "set-narration", beatId: "hook", text: "Hi" };
    const s = editorReducer(fresh(), { type: "APPEND_OP", op });
    expect(s.buffer).toEqual([op]);
  });

  it("APPEND_OP coalesces same-target narration", () => {
    let s = fresh();
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "hook", text: "v1" } });
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "hook", text: "v2" } });
    expect(s.buffer).toHaveLength(1);
    expect(s.buffer[0]).toMatchObject({ text: "v2" });
  });

  it("APPEND_OP does NOT coalesce different-beat narration", () => {
    let s = fresh();
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "hook", text: "a" } });
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "scene", text: "b" } });
    expect(s.buffer).toHaveLength(2);
  });

  it("APPEND_OP coalesces same-target clip trim", () => {
    let s = fresh();
    s = editorReducer(s, { type: "APPEND_OP", op: {
      op: "set-clip-trim", kind: "product-beat", index: 0,
      start_seconds: 1, duration_seconds: 2,
    }});
    s = editorReducer(s, { type: "APPEND_OP", op: {
      op: "set-clip-trim", kind: "product-beat", index: 0,
      start_seconds: 1.5, duration_seconds: 2.5,
    }});
    expect(s.buffer).toHaveLength(1);
    expect(s.buffer[0]).toMatchObject({ start_seconds: 1.5 });
  });

  it("APPEND_OP coalescing preserves order when replacing", () => {
    let s = fresh();
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "a", text: "1" } });
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "b", text: "2" } });
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "a", text: "1b" } });
    expect(s.buffer.map(o => (o as any).beatId)).toEqual(["a", "b"]);
    expect((s.buffer[0] as any).text).toBe("1b");
  });

  it("CLEAR_BUFFER empties the queue", () => {
    let s = fresh();
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "h", text: "x" } });
    s = editorReducer(s, { type: "CLEAR_BUFFER" });
    expect(s.buffer).toEqual([]);
  });

  it("REPLACE_SPEC swaps spec and clears buffer", () => {
    let s = fresh();
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "h", text: "x" } });
    const newSpec: ProgramSpec = { ...spec, name: "Renamed" };
    s = editorReducer(s, { type: "REPLACE_SPEC", spec: newSpec });
    expect(s.spec.name).toBe("Renamed");
    expect(s.buffer).toEqual([]);
  });

  it("SAVE_START / SAVE_OK / SAVE_ERROR transition save state", () => {
    let s = fresh();
    s = editorReducer(s, { type: "SAVE_START" });
    expect(s.saveState.status).toBe("saving");
    s = editorReducer(s, { type: "SAVE_OK", at: 1234 });
    expect(s.saveState).toEqual({ status: "saved", at: 1234 });
    s = editorReducer(s, { type: "SAVE_ERROR", message: "boom" });
    expect(s.saveState).toEqual({ status: "error", message: "boom" });
  });
});
```

- [ ] **Step 2: Run tests (expect missing-module fail)**

Run: `bun run test -- src/components/videos/__tests__/editorReducer.test.ts`
Expected: FAIL — cannot resolve `../editorReducer`

- [ ] **Step 3: Implement `editorReducer.ts`**

Create `frontend/src/components/videos/editorReducer.ts`:

```ts
import type { EditorState, PendingChange, ProgramSpec, WidgetRef } from "./types";
import { opCoalesceKey } from "./types";

export type EditorAction =
  | { type: "OPEN_DRAWER"; target: WidgetRef }
  | { type: "CLOSE_DRAWER" }
  | { type: "APPEND_OP"; op: PendingChange }
  | { type: "CLEAR_BUFFER" }
  | { type: "REPLACE_SPEC"; spec: ProgramSpec }
  | { type: "SAVE_START" }
  | { type: "SAVE_OK"; at: number }
  | { type: "SAVE_ERROR"; message: string };

export function initialEditorState(spec: ProgramSpec): EditorState {
  return { spec, buffer: [], drawerTarget: null, saveState: { status: "idle" } };
}

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "OPEN_DRAWER":
      return { ...state, drawerTarget: action.target };
    case "CLOSE_DRAWER":
      return { ...state, drawerTarget: null };
    case "APPEND_OP": {
      const key = opCoalesceKey(action.op);
      const existingIdx = state.buffer.findIndex(o => opCoalesceKey(o) === key);
      if (existingIdx >= 0) {
        const next = state.buffer.slice();
        next[existingIdx] = action.op;
        return { ...state, buffer: next };
      }
      return { ...state, buffer: [...state.buffer, action.op] };
    }
    case "CLEAR_BUFFER":
      return { ...state, buffer: [] };
    case "REPLACE_SPEC":
      return { ...state, spec: action.spec, buffer: [], drawerTarget: null };
    case "SAVE_START":
      return { ...state, saveState: { status: "saving" } };
    case "SAVE_OK":
      return { ...state, saveState: { status: "saved", at: action.at } };
    case "SAVE_ERROR":
      return { ...state, saveState: { status: "error", message: action.message } };
  }
}
```

- [ ] **Step 4: Run tests**

Run: `bun run test -- src/components/videos/__tests__/editorReducer.test.ts`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/videos/editorReducer.ts \
        frontend/src/components/videos/__tests__/editorReducer.test.ts
git commit -m "videos(editor): editorReducer with coalescing buffer + save state machine"
```

---

## Phase C — Frontend API client + context provider

### Task 8: API client extensions

**Files:**
- Modify: `frontend/src/api/videos.ts`

- [ ] **Step 1: Add types + functions**

At the bottom of `frontend/src/api/videos.ts`, append:

```ts
// ───────── edit-batch ─────────

export type EditBatchOp =
  | { op: "set-clip-trim"; kind: "scene-clip" | "product-beat"; index: number;
      start_seconds: number; duration_seconds: number }
  | { op: "set-clip-asset"; kind: "scene-clip" | "product-beat"; index: number; alias: string }
  | { op: "set-narration"; beatId: string; text: string }
  | { op: "set-stat"; path: string; big?: string; caption?: string; source?: string };

export interface EditBatchResult {
  ok: boolean;
  applied: number;
  message: string;
}

export function submitEditBatch(
  ws: string, p: string, r: string, ops: EditBatchOp[],
): Promise<EditBatchResult> {
  return v2Fetch(`${runBase(ws, p, r)}/edit-batch`, {
    method: "POST",
    body: JSON.stringify({ ops }),
  });
}

// ───────── spec read (for the editor) ─────────

// Returns the raw spec.yaml content as a JS object. The editor reads
// the parsed form from the existing /programs/<slug>/runs/<id> endpoint
// (extended below to include spec_yaml) — see Task 9 in the plan.
```

Note: we don't add a new endpoint for spec read — Task 9 extends an existing one.

- [ ] **Step 2: Confirm types compile**

Run: `bunx tsc -b --noEmit`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/videos.ts
git commit -m "videos(api-client): submitEditBatch + EditBatchOp type"
```

---

### Task 9: Expose parsed spec via run-detail endpoint

The frontend needs the parsed YAML to render beat cards. Extend `RunDetail` so the GET endpoint already in use returns the spec body.

**Files:**
- Modify: `apps/videos/schemas.py`
- Modify: `apps/videos/api.py`
- Modify: `apps/videos/service.py`
- Modify: `apps/videos/tests/test_api.py`
- Modify: `frontend/src/api/videos.ts`

- [ ] **Step 1: Write failing test**

Append to `apps/videos/tests/test_api.py`:

```python
@pytest.mark.django_db
def test_get_run_detail_includes_parsed_spec(member_client, videos_root, fake_drive):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert "spec" in body
    assert body["spec"]["slug"] == "demo"
    assert "scene" in body["spec"]
```

- [ ] **Step 2: Run test (fails — `spec` not in response)**

Run: `pytest apps/videos/tests/test_api.py::test_get_run_detail_includes_parsed_spec -v`
Expected: FAIL

- [ ] **Step 3: Add `spec` field to `RunDetailOut`**

In `apps/videos/schemas.py`, find the existing `RunDetailOut` (search for `class RunDetail`) and add a `spec` field of type `dict | None = None`. Show:

```python
class RunDetailOut(StrictModel):
    # ...existing fields...
    spec: dict | None = None
```

- [ ] **Step 4: Populate `spec` in the run-detail view**

In `apps/videos/service.py`, find the function that builds `RunDetailOut` (search for `run_detail` or `RunDetail`). Add a helper:

```python
def read_parsed_spec(workspace: Workspace, slug: str, run_id: str) -> dict | None:
    """Return the spec.yaml parsed via ruamel (round-trip safe). None if
    the spec doesn't exist."""
    layout, client = layout_for(workspace)
    raw = drive.read_spec(layout, client, slug, run_id)
    if raw is None:
        return None
    return _yaml().load(raw)
```

Then in the view body (in `apps/videos/api.py`), populate `spec=service.read_parsed_spec(workspace, program_slug, run_id)` in the `RunDetailOut(...)` constructor call.

- [ ] **Step 5: Update `RunDetail` type on the frontend**

In `frontend/src/api/videos.ts`, find the `RunDetail` interface (line 87) and add:

```ts
export interface RunDetail {
  // ...existing fields...
  spec: ProgramSpec | null;
}
```

Add the import at the top of `videos.ts`:

```ts
import type { ProgramSpec } from "@/components/videos/types";
```

- [ ] **Step 6: Run backend + frontend type checks**

```bash
pytest apps/videos/tests/test_api.py::test_get_run_detail_includes_parsed_spec -v
bunx tsc -b --noEmit
```
Expected: both pass

- [ ] **Step 7: Commit**

```bash
git add apps/videos/schemas.py apps/videos/api.py apps/videos/service.py \
        apps/videos/tests/test_api.py frontend/src/api/videos.ts
git commit -m "videos: expose parsed spec via GET /runs/{run_id} for editor consumption"
```

---

### Task 10: `BeatEditorContext` + `BeatEditor` skeleton

**Files:**
- Create: `frontend/src/components/videos/BeatEditorContext.tsx`
- Create: `frontend/src/components/videos/BeatEditor.tsx`

- [ ] **Step 1: Create the context**

Create `frontend/src/components/videos/BeatEditorContext.tsx`:

```tsx
import { createContext, useContext, useMemo, useReducer, type ReactNode } from "react";
import { applyOps } from "./applyOps";
import { editorReducer, initialEditorState, type EditorAction } from "./editorReducer";
import type { EditorState, ProgramSpec } from "./types";

interface ContextValue {
  state: EditorState;
  effectiveSpec: ProgramSpec;
  dispatch: (a: EditorAction) => void;
  programSlug: string;
  runId: string;
  workspaceSlug: string;
}

const Ctx = createContext<ContextValue | null>(null);

interface Props {
  workspaceSlug: string;
  programSlug: string;
  runId: string;
  spec: ProgramSpec;
  children: ReactNode;
}

export function BeatEditorProvider({ workspaceSlug, programSlug, runId, spec, children }: Props) {
  const [state, dispatch] = useReducer(editorReducer, spec, initialEditorState);
  const effectiveSpec = useMemo(
    () => applyOps(state.spec, state.buffer),
    [state.spec, state.buffer],
  );
  const value: ContextValue = { state, effectiveSpec, dispatch, programSlug, runId, workspaceSlug };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBeatEditor(): ContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useBeatEditor must be used inside <BeatEditorProvider>");
  return v;
}
```

- [ ] **Step 2: Create the top-level `BeatEditor` component**

Create `frontend/src/components/videos/BeatEditor.tsx`:

```tsx
import { BeatEditorProvider } from "./BeatEditorContext";
import { BeatEditorTopBar } from "./BeatEditorTopBar";
import { TimelineStrip } from "./TimelineStrip";
import { FinalVideoPlayer } from "./FinalVideoPlayer";
import { BeatList } from "./BeatList";
import { EditDrawer } from "./drawer/EditDrawer";
import type { ProgramSpec } from "./types";

interface Props {
  workspaceSlug: string;
  programSlug: string;
  runId: string;
  spec: ProgramSpec;
  // Bubbles to the page so the Re-render button can refetch if needed.
  onSpecRefetched?: (spec: ProgramSpec) => void;
}

export function BeatEditor({ workspaceSlug, programSlug, runId, spec, onSpecRefetched }: Props) {
  return (
    <BeatEditorProvider
      workspaceSlug={workspaceSlug}
      programSlug={programSlug}
      runId={runId}
      spec={spec}
    >
      <div className="flex flex-col gap-4">
        <BeatEditorTopBar onSpecRefetched={onSpecRefetched} />
        <TimelineStrip />
        <FinalVideoPlayer />
        <BeatList />
        <EditDrawer />
      </div>
    </BeatEditorProvider>
  );
}
```

- [ ] **Step 3: Stub the child components**

The child components don't exist yet — they're built in later tasks. Create minimal stubs so the file imports resolve:

Create each of these one-line stubs (they get replaced in later tasks):

```tsx
// frontend/src/components/videos/BeatEditorTopBar.tsx
export function BeatEditorTopBar(_: { onSpecRefetched?: unknown }) { return <div data-testid="topbar-stub" />; }
```

```tsx
// frontend/src/components/videos/TimelineStrip.tsx
export function TimelineStrip() { return <div data-testid="timeline-stub" />; }
```

```tsx
// frontend/src/components/videos/FinalVideoPlayer.tsx
export function FinalVideoPlayer() { return <div data-testid="finalplayer-stub" />; }
```

```tsx
// frontend/src/components/videos/BeatList.tsx
export function BeatList() { return <div data-testid="beatlist-stub" />; }
```

```tsx
// frontend/src/components/videos/drawer/EditDrawer.tsx
export function EditDrawer() { return null; }
```

- [ ] **Step 4: Type check**

Run: `bunx tsc -b --noEmit`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/videos/BeatEditorContext.tsx \
        frontend/src/components/videos/BeatEditor.tsx \
        frontend/src/components/videos/BeatEditorTopBar.tsx \
        frontend/src/components/videos/TimelineStrip.tsx \
        frontend/src/components/videos/FinalVideoPlayer.tsx \
        frontend/src/components/videos/BeatList.tsx \
        frontend/src/components/videos/drawer/EditDrawer.tsx
git commit -m "videos(editor): BeatEditor + context provider + child stubs"
```

---

### Task 11: Mount `<BeatEditor>` in `VideoExplorerPage` behind feature flag

**Files:**
- Modify: `config/settings/base.py`
- Modify: `apps/common/views.py` (or wherever the bootstrap-settings dict for the frontend lives — see Step 1)
- Modify: `frontend/src/pages/VideoExplorerPage.tsx`

- [ ] **Step 1: Find the frontend-exposed settings dict**

Run: `grep -rn 'BOOTSTRAP\|bootstrap_settings\|inject_settings' apps/ | head -5`

If a `bootstrap_settings()` or similar dict exists, add the flag there. If not, expose via the existing settings-from-Django pattern (search `frontend/src/` for how `BASE_URL` or other env-derived values are read).

Document the path you found in your commit message.

- [ ] **Step 2: Add the Django setting**

In `config/settings/base.py`, near other `ACE_*` settings:

```python
# Feature flag — flip to True once the React beat editor is ready for general
# use. When False, VideoExplorerPage falls back to the iframe-served HTML.
ACE_VIDEO_BEAT_EDITOR_REACT = env.bool("ACE_VIDEO_BEAT_EDITOR_REACT", default=False)
```

- [ ] **Step 3: Plumb the flag to the frontend**

In whatever module exposes Django settings to the SPA bootstrap (likely a context processor or a `/settings.json` endpoint), include `ACE_VIDEO_BEAT_EDITOR_REACT`. Add a TypeScript reader for it, e.g. extend `frontend/src/lib/settings.ts` (or wherever `BASE_URL` lives) with:

```ts
export const featureBeatEditorReact: boolean = Boolean(
  (window as any).__ACE_SETTINGS?.ACE_VIDEO_BEAT_EDITOR_REACT,
);
```

If no such module exists, create `frontend/src/lib/features.ts` with the export above and a comment explaining how the flag is plumbed.

- [ ] **Step 4: Gate the iframe vs `<BeatEditor>`**

In `frontend/src/pages/VideoExplorerPage.tsx`, find the iframe element (around `frontend/src/pages/VideoExplorerPage.tsx:302`). Replace the rendering branch with:

```tsx
import { BeatEditor } from "@/components/videos/BeatEditor";
import { featureBeatEditorReact } from "@/lib/features";

// ... inside the component, near where the iframe is currently rendered:

{featureBeatEditorReact && runDetail?.spec ? (
  <BeatEditor
    workspaceSlug={workspaceSlug}
    programSlug={programSlug}
    runId={runId}
    spec={runDetail.spec}
    onSpecRefetched={(s) => setRunDetail((rd) => rd ? { ...rd, spec: s } : rd)}
  />
) : (
  <iframe
    ref={iframeRef}
    src={/* ...existing... */}
  />
)}
```

Match the existing JSX shape — only replace the conditional rendering block.

- [ ] **Step 5: Confirm both paths still type-check + page renders**

```bash
bunx tsc -b --noEmit
```

Manually verify in dev: with flag off, iframe renders (existing behavior); with flag on, the React stubs render (will show `<div data-testid="topbar-stub" />` etc).

- [ ] **Step 6: Commit**

```bash
git add config/settings/base.py frontend/src/lib/features.ts \
        frontend/src/pages/VideoExplorerPage.tsx
git commit -m "videos(editor): mount React BeatEditor behind ACE_VIDEO_BEAT_EDITOR_REACT flag"
```

---

## Phase D — Read-only display components

### Task 12: `<TimelineStrip>` (read-only)

**Files:**
- Modify: `frontend/src/components/videos/TimelineStrip.tsx`

- [ ] **Step 1: Replace the stub with the real component**

```tsx
import { useBeatEditor } from "./BeatEditorContext";
import { opCoalesceKey } from "./types";

// Plain-language labels and kind→color map mirror build-clip-explorer.ts:113.
// Keep in sync if the framework adds new BeatKinds.
const SECTION_LABELS: Record<string, string> = {
  hook: "Opening tagline", cycle: "How Connect works", handoff: "Program handoff",
  scene: "Field footage", problem: "Headline stat",
  product: "Connect app walkthrough", impact: "Results numbers", cta: "End card",
};
const KIND_COLORS: Record<string, string> = {
  intro_hook: "#3843D0", intro_cycle: "#3843D0", intro_handoff: "#3843D0",
  body_scene: "#22A06B", body_problem_stat: "#E45A3A",
  body_product_beats: "#FEAF31", body_impact_stats: "#22A06B",
  outro_cta: "#3843D0",
};

export function TimelineStrip() {
  const { state, effectiveSpec } = useBeatEditor();
  const beats = effectiveSpec.beats ?? [];
  const total = beats.reduce((s, b) => s + b.seconds, 0) || 1;

  // A beat is "dirty" if buffer has any op targeting it.
  const dirtyBeats = new Set(
    state.buffer
      .map((op) => {
        const k = opCoalesceKey(op);
        if (k.startsWith("set-narration:")) return k.split(":")[1];
        if (k.startsWith("set-stat:problem")) return "problem";
        if (k.startsWith("set-stat:impact")) return "impact";
        // clip ops live in scene/product
        if (k.includes("scene-clip")) return "scene";
        if (k.includes("product-beat")) return "product";
        return null;
      })
      .filter(Boolean) as string[],
  );

  let cursor = 0;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        {beats.map((b) => (
          <span key={b.id} className="inline-flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: KIND_COLORS[b.kind] ?? "#3843D0" }}
            />
            {SECTION_LABELS[b.id] ?? b.id}
          </span>
        ))}
      </div>
      <div className="relative h-4 w-full overflow-hidden rounded bg-muted">
        {beats.map((b) => {
          const left = (cursor / total) * 100;
          const width = (b.seconds / total) * 100;
          cursor += b.seconds;
          return (
            <button
              type="button"
              key={b.id}
              className="absolute top-0 bottom-0"
              style={{
                left: `${left}%`, width: `${width}%`,
                background: KIND_COLORS[b.kind] ?? "#3843D0",
                opacity: 0.92,
                outline: dirtyBeats.has(b.id) ? "2px solid #FBBF24" : undefined,
                outlineOffset: -2,
              }}
              title={`${SECTION_LABELS[b.id] ?? b.id} · ${b.seconds.toFixed(1)}s`}
              onClick={() => {
                document
                  .querySelector(`[data-beat-id="${b.id}"]`)
                  ?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
            />
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type check + visual verify**

```bash
bunx tsc -b --noEmit
```

With the flag on, the timeline should render colored bars for each beat.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/videos/TimelineStrip.tsx
git commit -m "videos(editor): TimelineStrip with beat colors + click-to-jump + dirty highlight"
```

---

### Task 13: `<FinalVideoPlayer>`

**Files:**
- Modify: `frontend/src/components/videos/FinalVideoPlayer.tsx`

- [ ] **Step 1: Implement**

```tsx
import { useBeatEditor } from "./BeatEditorContext";

export function FinalVideoPlayer() {
  const { workspaceSlug, programSlug, runId } = useBeatEditor();
  const src = `/api/w/${workspaceSlug}/videos/programs/${programSlug}/runs/${runId}/media/final.mp4`;
  return (
    <div className="w-full">
      <video
        id="final-video"
        controls
        preload="metadata"
        className="w-full rounded-md border bg-black"
        src={src}
      />
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/videos/FinalVideoPlayer.tsx
git commit -m "videos(editor): FinalVideoPlayer via serve_media"
```

---

### Task 14: `<BeatList>` + `<BeatCard>` (read-only shell)

**Files:**
- Modify: `frontend/src/components/videos/BeatList.tsx`
- Create: `frontend/src/components/videos/BeatCard.tsx`

- [ ] **Step 1: Implement `<BeatCard>` shell**

Create `frontend/src/components/videos/BeatCard.tsx`:

```tsx
import { useBeatEditor } from "./BeatEditorContext";
import { opCoalesceKey, type PendingChange } from "./types";
import type { ReactNode } from "react";

const SECTION_LABELS: Record<string, { name: string; subtitle: string }> = {
  hook: { name: "Opening tagline", subtitle: "Headline that frames the video." },
  cycle: { name: "How Connect works", subtitle: "Learn → Deliver → Verify → Pay cycle." },
  handoff: { name: "Program handoff", subtitle: "Names this specific program." },
  scene: { name: "Field footage", subtitle: "Real footage from the program location." },
  problem: { name: "Headline stat", subtitle: "One big number that frames the problem." },
  product: { name: "Connect app walkthrough", subtitle: "Short phone-frame clips." },
  impact: { name: "Results numbers", subtitle: "Two big numbers — what the program delivered." },
  cta: { name: "End card", subtitle: "Logo + tagline + 'become a partner'." },
};

interface Props {
  beatId: string;
  kind: string;
  startSec: number;
  endSec: number;
  children: ReactNode;
}

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function beatIsDirty(beatId: string, buffer: PendingChange[]): boolean {
  return buffer.some((op) => {
    const k = opCoalesceKey(op);
    if (k === `set-narration:${beatId}`) return true;
    if (k === "set-stat:problem" && beatId === "problem") return true;
    if (k.startsWith("set-stat:impact") && beatId === "impact") return true;
    if (k.includes("scene-clip") && beatId === "scene") return true;
    if (k.includes("product-beat") && beatId === "product") return true;
    return false;
  });
}

export function BeatCard({ beatId, kind, startSec, endSec, children }: Props) {
  const { state } = useBeatEditor();
  const label = SECTION_LABELS[beatId] ?? { name: beatId, subtitle: "" };
  const dirty = beatIsDirty(beatId, state.buffer);
  return (
    <section
      data-beat-id={beatId}
      className="rounded-md border bg-card p-4"
      style={{
        outline: dirty ? "2px solid #FBBF24" : undefined,
        outlineOffset: -2,
      }}
    >
      <header className="mb-3 flex items-baseline gap-3">
        <h3 className="text-base font-semibold">{label.name}</h3>
        <span className="font-mono text-xs text-muted-foreground">
          {fmt(startSec)} → {fmt(endSec)} · {(endSec - startSec).toFixed(1)}s
        </span>
        {dirty && (
          <span className="ml-auto rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
            edited
          </span>
        )}
      </header>
      {label.subtitle && (
        <p className="mb-3 text-sm text-muted-foreground">{label.subtitle}</p>
      )}
      <div className="flex flex-col gap-3">{children}</div>
    </section>
  );
}
```

- [ ] **Step 2: Implement `<BeatList>`**

Replace stub at `frontend/src/components/videos/BeatList.tsx`:

```tsx
import { useBeatEditor } from "./BeatEditorContext";
import { BeatCard } from "./BeatCard";
import { ClipSlotWidget } from "./widgets/ClipSlotWidget";
import { NarrationWidget } from "./widgets/NarrationWidget";
import { StatsWidget } from "./widgets/StatsWidget";
import { BrandTemplateWidget } from "./widgets/BrandTemplateWidget";

export function BeatList() {
  const { effectiveSpec } = useBeatEditor();
  const beats = effectiveSpec.beats ?? [];
  let cursor = 0;
  return (
    <div className="flex flex-col gap-4">
      {beats.map((b) => {
        const startSec = cursor;
        const endSec = cursor + b.seconds;
        cursor += b.seconds;
        return (
          <BeatCard key={b.id} beatId={b.id} kind={b.kind} startSec={startSec} endSec={endSec}>
            <NarrationWidget beatId={b.id} />
            {renderKindBody(b.id, b.kind, effectiveSpec)}
          </BeatCard>
        );
      })}
    </div>
  );
}

function renderKindBody(beatId: string, kind: string, spec: ReturnType<typeof useBeatEditor>["effectiveSpec"]) {
  if (kind === "body_scene") {
    return (spec.scene?.clips ?? []).map((_, i) => (
      <ClipSlotWidget key={i} beatId={beatId} clipKind="scene-clip" index={i} />
    ));
  }
  if (kind === "body_product_beats") {
    return (spec.product?.beats ?? []).map((_, i) => (
      <ClipSlotWidget key={i} beatId={beatId} clipKind="product-beat" index={i} />
    ));
  }
  if (kind === "body_problem_stat") {
    return <StatsWidget beatId={beatId} path="problem" />;
  }
  if (kind === "body_impact_stats") {
    return (spec.impact ?? []).map((_, i) => (
      <StatsWidget key={i} beatId={beatId} path={`impact[${i}]`} />
    ));
  }
  return <BrandTemplateWidget beatId={beatId} kind={kind} />;
}
```

- [ ] **Step 3: Stub the widgets so imports resolve**

Create each (will be filled in next tasks):

```tsx
// frontend/src/components/videos/widgets/ClipSlotWidget.tsx
export function ClipSlotWidget(_: { beatId: string; clipKind: string; index: number }) {
  return <div data-testid="clip-stub">clip stub</div>;
}
```

```tsx
// frontend/src/components/videos/widgets/NarrationWidget.tsx
export function NarrationWidget(_: { beatId: string }) {
  return <div data-testid="narration-stub">narration stub</div>;
}
```

```tsx
// frontend/src/components/videos/widgets/StatsWidget.tsx
export function StatsWidget(_: { beatId: string; path: string }) {
  return <div data-testid="stats-stub">stats stub</div>;
}
```

```tsx
// frontend/src/components/videos/widgets/BrandTemplateWidget.tsx
export function BrandTemplateWidget(_: { beatId: string; kind: string }) {
  return <div data-testid="brand-stub">brand stub</div>;
}
```

- [ ] **Step 4: Type check + visual verify**

```bash
bunx tsc -b --noEmit
```

With the flag on, the editor should now render one BeatCard per beat with stub widget content inside.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/videos/BeatList.tsx \
        frontend/src/components/videos/BeatCard.tsx \
        frontend/src/components/videos/widgets/*.tsx
git commit -m "videos(editor): BeatList + BeatCard render shell with widget stubs"
```

---

### Task 15: Widget cards — `ClipSlotWidget`, `NarrationWidget`, `StatsWidget`, `BrandTemplateWidget`

**Files:**
- Modify: `frontend/src/components/videos/widgets/ClipSlotWidget.tsx`
- Modify: `frontend/src/components/videos/widgets/NarrationWidget.tsx`
- Modify: `frontend/src/components/videos/widgets/StatsWidget.tsx`
- Modify: `frontend/src/components/videos/widgets/BrandTemplateWidget.tsx`

- [ ] **Step 1: `ClipSlotWidget`**

```tsx
// frontend/src/components/videos/widgets/ClipSlotWidget.tsx
import { useBeatEditor } from "../BeatEditorContext";
import type { ClipObject } from "../types";

interface Props {
  beatId: string;
  clipKind: "scene-clip" | "product-beat";
  index: number;
}

function aliasFromRef(ref: string): string | null {
  if (typeof ref === "string" && ref.startsWith("@")) return ref.slice(1);
  return null;
}

export function ClipSlotWidget({ beatId, clipKind, index }: Props) {
  const { effectiveSpec, workspaceSlug, programSlug, runId, dispatch } = useBeatEditor();
  const slot = clipKind === "scene-clip"
    ? effectiveSpec.scene?.clips[index]
    : effectiveSpec.product?.beats[index];

  if (slot === undefined) return null;
  const ref = typeof slot === "string" ? slot : slot.asset;
  const obj: ClipObject = typeof slot === "string" ? { asset: slot } : slot;
  const alias = aliasFromRef(ref) ?? "(literal path)";
  const trim = (obj.start_seconds !== undefined && obj.duration_seconds !== undefined)
    ? `${obj.start_seconds.toFixed(1)}s → ${(obj.start_seconds + obj.duration_seconds).toFixed(1)}s · ${obj.duration_seconds.toFixed(1)}s`
    : "untrimmed";

  // Source-clip MP4 served by the existing serve_media endpoint.
  const mediaUrl = alias && alias !== "(literal path)"
    ? `/api/w/${workspaceSlug}/videos/programs/${programSlug}/runs/${runId}/media/${alias}.mp4`
    : null;

  return (
    <div
      className="cursor-pointer rounded border bg-muted/40 p-3 hover:border-primary"
      onClick={() =>
        dispatch({
          type: "OPEN_DRAWER",
          target: { kind: "clip-trim", clipKind, beatId, index },
        })
      }
    >
      <header className="mb-2 flex items-center gap-2">
        <code className="rounded bg-muted px-1.5 py-0.5 text-xs">@{alias}</code>
        <span className="ml-auto text-xs text-muted-foreground">click to edit</span>
      </header>
      {mediaUrl && (
        <video
          src={mediaUrl}
          preload="metadata"
          muted
          className="mb-2 aspect-video w-full rounded bg-black"
        />
      )}
      <div className="font-mono text-xs text-muted-foreground">{trim}</div>
    </div>
  );
}
```

- [ ] **Step 2: `NarrationWidget`**

```tsx
// frontend/src/components/videos/widgets/NarrationWidget.tsx
import { useBeatEditor } from "../BeatEditorContext";

export function NarrationWidget({ beatId }: { beatId: string }) {
  const { effectiveSpec, dispatch } = useBeatEditor();
  const text = effectiveSpec.narration?.by_beat?.[beatId] ?? "";
  const wordCount = text.trim() ? text.trim().split(/\s+/).length : 0;
  const estSec = Math.round((text.length / 15) * 10) / 10;

  return (
    <div
      className="cursor-pointer rounded border bg-muted/20 p-3 hover:border-primary"
      onClick={() => dispatch({ type: "OPEN_DRAWER", target: { kind: "narration", beatId } })}
    >
      <header className="mb-1 flex items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Voiceover
        </span>
        <span className="ml-auto text-xs text-muted-foreground">click to edit</span>
      </header>
      <p className={text.trim() ? "text-sm" : "text-sm italic text-muted-foreground"}>
        {text.trim() || "(no narration — click to add)"}
      </p>
      <div className="mt-1 text-xs text-muted-foreground">
        {wordCount} word{wordCount === 1 ? "" : "s"} · ~{estSec}s read
      </div>
    </div>
  );
}
```

- [ ] **Step 3: `StatsWidget`**

```tsx
// frontend/src/components/videos/widgets/StatsWidget.tsx
import { useBeatEditor } from "../BeatEditorContext";
import type { Stat } from "../types";

function resolveStat(spec: ReturnType<typeof useBeatEditor>["effectiveSpec"], path: string): Stat | null {
  if (path === "problem") return spec.problem ?? null;
  const m = /^impact\[(\d+)\]$/.exec(path);
  if (!m) return null;
  return spec.impact?.[parseInt(m[1], 10)] ?? null;
}

export function StatsWidget({ beatId, path }: { beatId: string; path: string }) {
  const { effectiveSpec, dispatch } = useBeatEditor();
  const stat = resolveStat(effectiveSpec, path);
  if (!stat) return null;
  return (
    <div
      className="cursor-pointer rounded border bg-muted/20 p-3 hover:border-primary"
      onClick={() => dispatch({ type: "OPEN_DRAWER", target: { kind: "stat", beatId, path } })}
    >
      <div className="flex items-baseline gap-3">
        <div className="text-3xl font-bold">{stat.big}</div>
        <div className="flex-1">
          <div className="text-sm">{stat.caption}</div>
          {stat.source && (
            <div className="mt-0.5 text-xs text-muted-foreground">source: {stat.source}</div>
          )}
        </div>
        <span className="text-xs text-muted-foreground">click to edit</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: `BrandTemplateWidget`**

```tsx
// frontend/src/components/videos/widgets/BrandTemplateWidget.tsx
const BRAND_DESCRIPTIONS: Record<string, string> = {
  intro_hook: 'Animated tagline: "Pay for verified service delivery, not planned activity."',
  intro_cycle: "Four-step cycle animation: Learn → Deliver → Verify → Pay.",
  intro_handoff: "Brand handoff card — uses program name from spec.yaml.",
  outro_cta: "End card — logo, tagline, 'Request a demo' link.",
};

export function BrandTemplateWidget({ kind }: { kind: string }) {
  return (
    <div className="rounded border border-dashed bg-muted/10 p-3">
      <div className="mb-1 flex items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Brand template · global
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        {BRAND_DESCRIPTIONS[kind] ?? "Brand-template beat — no per-program content."}
      </p>
      <button
        type="button"
        disabled
        title="Brand strings live in programs/_defaults.yaml. Per-program override coming later."
        className="mt-2 cursor-not-allowed text-xs text-muted-foreground underline opacity-60"
      >
        Edit globally
      </button>
    </div>
  );
}
```

- [ ] **Step 5: Type check + visual verify**

```bash
bunx tsc -b --noEmit
```

With the flag on, all widget cards should render with real content. Clicking opens nothing yet (EditDrawer is still a stub returning null).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/videos/widgets/*.tsx
git commit -m "videos(editor): per-widget cards (clip, narration, stats, brand)"
```

---

## Phase E — Edit drawer

### Task 16: `DrawerShell`, `ModalShell`, `EditDrawer` mode-switcher

**Files:**
- Create: `frontend/src/components/videos/drawer/DrawerShell.tsx`
- Create: `frontend/src/components/videos/drawer/ModalShell.tsx`
- Modify: `frontend/src/components/videos/drawer/EditDrawer.tsx`

- [ ] **Step 1: `DrawerShell`**

Create `frontend/src/components/videos/drawer/DrawerShell.tsx`:

```tsx
import { type ReactNode, useEffect } from "react";

interface Props {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footerActions: ReactNode;
}

export function DrawerShell({ open, title, onClose, children, footerActions }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/30"
        onClick={onClose}
        aria-hidden
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="fixed right-0 top-0 bottom-0 z-50 flex w-[480px] max-w-[90vw] flex-col bg-background shadow-xl"
      >
        <header className="border-b p-4">
          <h2 className="text-base font-semibold">{title}</h2>
        </header>
        <div className="flex-1 overflow-auto p-4">{children}</div>
        <footer className="flex items-center justify-end gap-2 border-t p-4">{footerActions}</footer>
      </aside>
    </>
  );
}
```

- [ ] **Step 2: `ModalShell` (same prop contract)**

Create `frontend/src/components/videos/drawer/ModalShell.tsx`:

```tsx
import { type ReactNode, useEffect } from "react";

interface Props {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footerActions: ReactNode;
}

export function ModalShell({ open, title, onClose, children, footerActions }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-2xl rounded-lg bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="border-b p-4">
          <h2 className="text-base font-semibold">{title}</h2>
        </header>
        <div className="max-h-[70vh] overflow-auto p-4">{children}</div>
        <footer className="flex items-center justify-end gap-2 border-t p-4">{footerActions}</footer>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: `EditDrawer` mode-switcher with kind dispatch**

Replace `frontend/src/components/videos/drawer/EditDrawer.tsx`:

```tsx
import { useBeatEditor } from "../BeatEditorContext";
import { DrawerShell } from "./DrawerShell";
import { ModalShell } from "./ModalShell";
import { ClipTrimPanel } from "./panels/ClipTrimPanel";
import { NarrationPanel } from "./panels/NarrationPanel";
import { StatPanel } from "./panels/StatPanel";

// Default shell. Swap to "modal" if the team prefers it after dogfooding.
const SHELL_MODE: "drawer" | "modal" = "drawer";

export function EditDrawer() {
  const { state, dispatch } = useBeatEditor();
  const target = state.drawerTarget;
  const close = () => dispatch({ type: "CLOSE_DRAWER" });

  if (!target) {
    // Render a closed shell so children's hooks stay stable across opens.
    return (
      <DrawerShell open={false} title="" onClose={close} footerActions={null}>
        {null}
      </DrawerShell>
    );
  }

  let title: string;
  let body: React.ReactNode;
  let footerActions: React.ReactNode;
  if (target.kind === "clip-trim") {
    title = `Trim ${target.clipKind} #${target.index + 1}`;
    body = <ClipTrimPanel
      clipKind={target.clipKind}
      index={target.index}
      onCommit={close}
      onCancel={close}
    />;
    footerActions = null;  // panel renders its own buttons
  } else if (target.kind === "narration") {
    title = `Voiceover — ${target.beatId}`;
    body = <NarrationPanel beatId={target.beatId} onCommit={close} onCancel={close} />;
    footerActions = null;
  } else {
    title = `Stat — ${target.path}`;
    body = <StatPanel path={target.path} onCommit={close} onCancel={close} />;
    footerActions = null;
  }

  const Shell = SHELL_MODE === "drawer" ? DrawerShell : ModalShell;
  return (
    <Shell open={true} title={title} onClose={close} footerActions={footerActions}>
      {body}
    </Shell>
  );
}
```

- [ ] **Step 4: Stub the panels**

Create stubs so imports resolve (filled in next tasks):

```tsx
// frontend/src/components/videos/drawer/panels/ClipTrimPanel.tsx
export function ClipTrimPanel(_: any) { return <div data-testid="cliptrim-stub" />; }
```
```tsx
// frontend/src/components/videos/drawer/panels/NarrationPanel.tsx
export function NarrationPanel(_: any) { return <div data-testid="narration-panel-stub" />; }
```
```tsx
// frontend/src/components/videos/drawer/panels/StatPanel.tsx
export function StatPanel(_: any) { return <div data-testid="stat-panel-stub" />; }
```

- [ ] **Step 5: Type check + visual verify**

```bash
bunx tsc -b --noEmit
```

Clicking a widget should now open the drawer with the stub panel inside; ESC and backdrop-click should close it.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/videos/drawer/*.tsx \
        frontend/src/components/videos/drawer/panels/*.tsx
git commit -m "videos(editor): DrawerShell + ModalShell + EditDrawer mode-switcher"
```

---

### Task 17: `<TrimBar>` reusable widget with fixed mouse handling

**Files:**
- Create: `frontend/src/components/videos/drawer/TrimBar.tsx`
- Create: `frontend/src/components/videos/__tests__/TrimBar.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/videos/__tests__/TrimBar.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TrimBar } from "../drawer/TrimBar";

function renderBar(props: Partial<Parameters<typeof TrimBar>[0]> = {}) {
  const onChange = vi.fn();
  const utils = render(
    <TrimBar
      sourceDuration={10}
      start={2}
      duration={4}
      onChange={onChange}
      {...props}
    />,
  );
  return { onChange, ...utils };
}

describe("TrimBar", () => {
  it("renders region positioned proportionally to source duration", () => {
    renderBar();
    const region = screen.getByTestId("trim-region");
    // start=2 of 10 = 20%; dur=4 of 10 = 40%
    expect(region.style.left).toBe("20%");
    expect(region.style.width).toBe("40%");
  });

  it("clamps start ≥ 0", () => {
    const { onChange } = renderBar({ start: 0, duration: 4 });
    const left = screen.getByTestId("trim-handle-left");
    // Mock a getBoundingClientRect for the bar.
    const bar = screen.getByTestId("trim-bar");
    vi.spyOn(bar, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, right: 200, bottom: 20, width: 200, height: 20, toJSON: () => ({}),
    } as DOMRect);
    fireEvent.pointerDown(left, { clientX: 0, pointerId: 1 });
    fireEvent.pointerMove(window, { clientX: -100, pointerId: 1 });
    fireEvent.pointerUp(window, { clientX: -100, pointerId: 1 });
    const calls = onChange.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    const last = calls[calls.length - 1][0];
    expect(last.start_seconds).toBeGreaterThanOrEqual(0);
  });

  it("clamps start + duration ≤ sourceDuration", () => {
    const { onChange } = renderBar({ start: 6, duration: 4 }); // 10s used of 10s
    const right = screen.getByTestId("trim-handle-right");
    const bar = screen.getByTestId("trim-bar");
    vi.spyOn(bar, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, right: 200, bottom: 20, width: 200, height: 20, toJSON: () => ({}),
    } as DOMRect);
    fireEvent.pointerDown(right, { clientX: 200, pointerId: 1 });
    fireEvent.pointerMove(window, { clientX: 400, pointerId: 1 });
    fireEvent.pointerUp(window, { clientX: 400, pointerId: 1 });
    const last = onChange.mock.calls.at(-1)![0];
    expect(last.start_seconds + last.duration_seconds).toBeLessThanOrEqual(10 + 0.001);
  });

  it("arrow key nudges focused handle by 0.1s", () => {
    const { onChange } = renderBar();
    const left = screen.getByTestId("trim-handle-left");
    left.focus();
    fireEvent.keyDown(left, { key: "ArrowRight" });
    const last = onChange.mock.calls.at(-1)![0];
    expect(last.start_seconds).toBeCloseTo(2.1, 3);
  });

  it("shift+arrow nudges by 1.0s", () => {
    const { onChange } = renderBar();
    const left = screen.getByTestId("trim-handle-left");
    left.focus();
    fireEvent.keyDown(left, { key: "ArrowRight", shiftKey: true });
    const last = onChange.mock.calls.at(-1)![0];
    expect(last.start_seconds).toBeCloseTo(3.0, 3);
  });
});
```

- [ ] **Step 2: Run tests (expect import-resolution fail)**

Run: `bun run test -- src/components/videos/__tests__/TrimBar.test.tsx`
Expected: FAIL — cannot resolve `../drawer/TrimBar`

- [ ] **Step 3: Implement `TrimBar`**

Create `frontend/src/components/videos/drawer/TrimBar.tsx`:

```tsx
import { useCallback, useRef, type PointerEvent as ReactPointerEvent } from "react";

interface Props {
  sourceDuration: number;
  start: number;
  duration: number;
  onChange: (next: { start_seconds: number; duration_seconds: number }) => void;
}

const MIN_DURATION = 0.3;
const NUDGE_SMALL = 0.1;
const NUDGE_LARGE = 1.0;

function clampValues(start: number, duration: number, sourceDuration: number) {
  const clampedStart = Math.max(0, Math.min(sourceDuration - MIN_DURATION, start));
  const maxDur = sourceDuration - clampedStart;
  const clampedDur = Math.max(MIN_DURATION, Math.min(maxDur, duration));
  return { start_seconds: clampedStart, duration_seconds: clampedDur };
}

export function TrimBar({ sourceDuration, start, duration, onChange }: Props) {
  const barRef = useRef<HTMLDivElement>(null);

  const leftPct = (start / sourceDuration) * 100;
  const widthPct = (duration / sourceDuration) * 100;

  const startDrag = useCallback(
    (mode: "left" | "right" | "move") => (e: ReactPointerEvent) => {
      e.preventDefault();
      const bar = barRef.current;
      if (!bar) return;
      const barRect = bar.getBoundingClientRect();
      const startX = e.clientX;
      const startStart = start;
      const startDur = duration;

      const onMove = (ev: PointerEvent) => {
        const dSec = ((ev.clientX - startX) / barRect.width) * sourceDuration;
        let nextStart = startStart;
        let nextDur = startDur;
        if (mode === "left") {
          nextStart = startStart + dSec;
          nextDur = startDur - dSec;
        } else if (mode === "right") {
          nextDur = startDur + dSec;
        } else {
          nextStart = startStart + dSec;
        }
        onChange(clampValues(nextStart, nextDur, sourceDuration));
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointercancel", onUp);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
    },
    [start, duration, sourceDuration, onChange],
  );

  const nudge = (handle: "left" | "right", direction: "+" | "-", amount: number) => {
    const sign = direction === "+" ? 1 : -1;
    if (handle === "left") {
      const nextStart = start + sign * amount;
      const nextDur = duration - sign * amount;
      onChange(clampValues(nextStart, nextDur, sourceDuration));
    } else {
      onChange(clampValues(start, duration + sign * amount, sourceDuration));
    }
  };

  const onKey = (handle: "left" | "right") => (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const amount = e.shiftKey ? NUDGE_LARGE : NUDGE_SMALL;
    nudge(handle, e.key === "ArrowRight" ? "+" : "-", amount);
  };

  return (
    <div
      ref={barRef}
      data-testid="trim-bar"
      className="relative h-9 select-none rounded bg-muted"
      style={{ touchAction: "none" }}
    >
      <div
        data-testid="trim-region"
        className="absolute inset-y-0 bg-primary/30 border-2 border-primary cursor-grab"
        style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
        onPointerDown={startDrag("move")}
      >
        <button
          type="button"
          data-testid="trim-handle-left"
          aria-label="Trim start handle"
          tabIndex={0}
          onPointerDown={startDrag("left")}
          onKeyDown={onKey("left")}
          className="absolute top-[-4px] bottom-[-4px] left-0 w-[14px] bg-primary border-2 border-background rounded-sm cursor-ew-resize focus:outline-2 focus:outline-amber-400"
        />
        <button
          type="button"
          data-testid="trim-handle-right"
          aria-label="Trim end handle"
          tabIndex={0}
          onPointerDown={startDrag("right")}
          onKeyDown={onKey("right")}
          className="absolute top-[-4px] bottom-[-4px] right-0 w-[14px] bg-primary border-2 border-background rounded-sm cursor-ew-resize focus:outline-2 focus:outline-amber-400"
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `bun run test -- src/components/videos/__tests__/TrimBar.test.tsx`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/videos/drawer/TrimBar.tsx \
        frontend/src/components/videos/__tests__/TrimBar.test.tsx
git commit -m "videos(editor): TrimBar with window-level pointer listeners + keyboard nudge"
```

---

### Task 18: `<ClipTrimPanel>` (uses TrimBar)

**Files:**
- Modify: `frontend/src/components/videos/drawer/panels/ClipTrimPanel.tsx`

- [ ] **Step 1: Implement**

```tsx
// frontend/src/components/videos/drawer/panels/ClipTrimPanel.tsx
import { useEffect, useRef, useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";
import { TrimBar } from "../TrimBar";

interface Props {
  clipKind: "scene-clip" | "product-beat";
  index: number;
  onCommit: () => void;
  onCancel: () => void;
}

function aliasFromRef(r: string): string | null {
  return r.startsWith("@") ? r.slice(1) : null;
}

export function ClipTrimPanel({ clipKind, index, onCommit, onCancel }: Props) {
  const { effectiveSpec, workspaceSlug, programSlug, runId, dispatch } = useBeatEditor();
  const slot = clipKind === "scene-clip"
    ? effectiveSpec.scene?.clips[index]
    : effectiveSpec.product?.beats[index];

  const initial = (() => {
    if (slot === undefined) return null;
    const obj = typeof slot === "string" ? { asset: slot } : slot;
    return {
      asset: obj.asset,
      start: obj.start_seconds ?? 0,
      duration: obj.duration_seconds ?? 0,
    };
  })();

  const [draft, setDraft] = useState(initial);
  const [sourceDuration, setSourceDuration] = useState<number>(0);
  const videoRef = useRef<HTMLVideoElement>(null);

  // Probe the source video for its real duration on load.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onMeta = () => {
      setSourceDuration(v.duration);
      // If draft has no duration set (untrimmed clip), default to full clip.
      setDraft((d) => d && d.duration === 0 ? { ...d, duration: v.duration } : d);
    };
    v.addEventListener("loadedmetadata", onMeta);
    return () => v.removeEventListener("loadedmetadata", onMeta);
  }, []);

  // Live-seek the preview to the trim IN-point.
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !draft || v.readyState < 1) return;
    if (!v.paused) v.pause();
    const safe = Math.max(0, Math.min((v.duration || sourceDuration) - 0.05, draft.start));
    try { v.currentTime = safe; } catch { /* swallow */ }
  }, [draft?.start, sourceDuration]);

  if (!initial || !draft) return <div>(clip not found)</div>;

  const alias = aliasFromRef(initial.asset);
  const src = alias
    ? `/api/w/${workspaceSlug}/videos/programs/${programSlug}/runs/${runId}/media/${alias}.mp4`
    : null;

  const commit = () => {
    dispatch({
      type: "APPEND_OP",
      op: {
        op: "set-clip-trim", kind: clipKind, index,
        start_seconds: parseFloat(draft.start.toFixed(2)),
        duration_seconds: parseFloat(draft.duration.toFixed(2)),
      },
    });
    onCommit();
  };

  const dirty = draft.start !== initial.start || draft.duration !== initial.duration;

  return (
    <div className="flex flex-col gap-3">
      {src && (
        <video
          ref={videoRef}
          src={src}
          controls
          preload="metadata"
          className="aspect-video w-full rounded bg-black"
        />
      )}
      <TrimBar
        sourceDuration={sourceDuration || 1}
        start={draft.start}
        duration={draft.duration}
        onChange={(next) => setDraft({ ...draft, start: next.start_seconds, duration: next.duration_seconds })}
      />
      <div className="flex items-center gap-3 font-mono text-xs text-muted-foreground">
        <label className="flex items-center gap-1">
          start
          <input
            type="number" step="0.1" min={0} max={sourceDuration}
            value={draft.start.toFixed(2)}
            onChange={(e) => setDraft({ ...draft, start: parseFloat(e.target.value) || 0 })}
            className="w-20 rounded border bg-background px-1 py-0.5"
          />
          s
        </label>
        <label className="flex items-center gap-1">
          duration
          <input
            type="number" step="0.1" min={0.3} max={sourceDuration}
            value={draft.duration.toFixed(2)}
            onChange={(e) => setDraft({ ...draft, duration: parseFloat(e.target.value) || 0 })}
            className="w-20 rounded border bg-background px-1 py-0.5"
          />
          s
        </label>
      </div>
      <div className="mt-2 flex justify-end gap-2">
        <button type="button" onClick={onCancel}
                className="rounded border px-3 py-1.5 text-sm">
          Cancel
        </button>
        <button type="button" onClick={commit} disabled={!dirty}
                className="rounded bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          Done
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type check + visual verify**

```bash
bunx tsc -b --noEmit
```

Clicking a clip card should open the drawer; trim bar drags should update start/duration; Done should commit to the buffer and the BeatCard should sprout an "edited" pill.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/videos/drawer/panels/ClipTrimPanel.tsx
git commit -m "videos(editor): ClipTrimPanel with live-seek preview + numeric inputs"
```

---

### Task 19: `<NarrationPanel>` + tests

**Files:**
- Modify: `frontend/src/components/videos/drawer/panels/NarrationPanel.tsx`
- Create: `frontend/src/components/videos/__tests__/NarrationPanel.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/videos/__tests__/NarrationPanel.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { NarrationPanel } from "../drawer/panels/NarrationPanel";
import { BeatEditorProvider } from "../BeatEditorContext";
import type { ProgramSpec } from "../types";

const spec: ProgramSpec = {
  slug: "demo", name: "Demo",
  narration: { by_beat: { hook: "Initial text" } },
};

function renderPanel(onCommit = vi.fn(), onCancel = vi.fn()) {
  return render(
    <BeatEditorProvider workspaceSlug="ws1" programSlug="demo" runId="run-001" spec={spec}>
      <NarrationPanel beatId="hook" onCommit={onCommit} onCancel={onCancel} />
    </BeatEditorProvider>,
  );
}

describe("NarrationPanel", () => {
  it("prefills the textarea with current text", () => {
    renderPanel();
    expect(screen.getByRole("textbox")).toHaveValue("Initial text");
  });

  it("Done is disabled when text is unchanged", () => {
    renderPanel();
    expect(screen.getByRole("button", { name: /Done/i })).toBeDisabled();
  });

  it("typing enables Done", () => {
    renderPanel();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "New text" } });
    expect(screen.getByRole("button", { name: /Done/i })).toBeEnabled();
  });

  it("clicking Done calls onCommit", () => {
    const onCommit = vi.fn();
    renderPanel(onCommit);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "New text" } });
    fireEvent.click(screen.getByRole("button", { name: /Done/i }));
    expect(onCommit).toHaveBeenCalled();
  });

  it("Cmd+Enter submits", () => {
    const onCommit = vi.fn();
    renderPanel(onCommit);
    const ta = screen.getByRole("textbox");
    fireEvent.change(ta, { target: { value: "New text" } });
    fireEvent.keyDown(ta, { key: "Enter", metaKey: true });
    expect(onCommit).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests (expect fail)**

Run: `bun run test -- src/components/videos/__tests__/NarrationPanel.test.tsx`
Expected: FAIL (stub doesn't render anything matching the assertions)

- [ ] **Step 3: Implement `NarrationPanel`**

```tsx
// frontend/src/components/videos/drawer/panels/NarrationPanel.tsx
import { useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";

interface Props {
  beatId: string;
  onCommit: () => void;
  onCancel: () => void;
}

export function NarrationPanel({ beatId, onCommit, onCancel }: Props) {
  const { effectiveSpec, dispatch } = useBeatEditor();
  const initial = effectiveSpec.narration?.by_beat?.[beatId] ?? "";
  const [text, setText] = useState(initial);
  const dirty = text !== initial;

  const voice = effectiveSpec.voice?.voice_id ?? "(default)";
  const model = effectiveSpec.voice?.model ?? "(default)";
  const wordCount = text.trim() ? text.trim().split(/\s+/).length : 0;
  const estSec = Math.round((text.length / 15) * 10) / 10;

  const commit = () => {
    if (!dirty) return;
    dispatch({ type: "APPEND_OP", op: { op: "set-narration", beatId, text } });
    onCommit();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      commit();
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-muted-foreground">
        Voice <code className="rounded bg-muted px-1">{voice}</code> ·
        model <code className="rounded bg-muted px-1">{model}</code>
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        rows={8}
        className="w-full rounded border bg-background p-2 font-sans text-sm"
      />
      <div className="text-xs text-muted-foreground">
        {wordCount} word{wordCount === 1 ? "" : "s"} · ~{estSec}s read
      </div>
      <p className="text-xs text-muted-foreground">
        Identical text reuses the cached audio — no resynth on Re-render.
      </p>
      <div className="mt-2 flex justify-end gap-2">
        <button type="button" onClick={onCancel}
                className="rounded border px-3 py-1.5 text-sm">
          Cancel
        </button>
        <button type="button" onClick={commit} disabled={!dirty}
                className="rounded bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          Done
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `bun run test -- src/components/videos/__tests__/NarrationPanel.test.tsx`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/videos/drawer/panels/NarrationPanel.tsx \
        frontend/src/components/videos/__tests__/NarrationPanel.test.tsx
git commit -m "videos(editor): NarrationPanel with Cmd+Enter shortcut + tests"
```

---

### Task 20: `<StatPanel>` + tests

**Files:**
- Modify: `frontend/src/components/videos/drawer/panels/StatPanel.tsx`
- Create: `frontend/src/components/videos/__tests__/StatPanel.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/videos/__tests__/StatPanel.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { StatPanel } from "../drawer/panels/StatPanel";
import { BeatEditorProvider } from "../BeatEditorContext";
import type { ProgramSpec } from "../types";

const spec: ProgramSpec = {
  slug: "demo", name: "Demo",
  narration: { by_beat: {} },
  problem: { big: "29%", caption: "old caption", source: "NDHS 2018" },
  impact: [{ big: "$1", caption: "a" }],
};

function renderPanel(path: string, onCommit = vi.fn(), onCancel = vi.fn()) {
  return render(
    <BeatEditorProvider workspaceSlug="ws1" programSlug="demo" runId="run-001" spec={spec}>
      <StatPanel path={path} onCommit={onCommit} onCancel={onCancel} />
    </BeatEditorProvider>,
  );
}

describe("StatPanel", () => {
  it("prefills problem fields", () => {
    renderPanel("problem");
    expect(screen.getByLabelText(/big/i)).toHaveValue("29%");
    expect(screen.getByLabelText(/caption/i)).toHaveValue("old caption");
  });

  it("Done is disabled until a field changes", () => {
    renderPanel("problem");
    expect(screen.getByRole("button", { name: /Done/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/big/i), { target: { value: "31%" } });
    expect(screen.getByRole("button", { name: /Done/i })).toBeEnabled();
  });

  it("clicking Done calls onCommit", () => {
    const onCommit = vi.fn();
    renderPanel("problem", onCommit);
    fireEvent.change(screen.getByLabelText(/big/i), { target: { value: "31%" } });
    fireEvent.click(screen.getByRole("button", { name: /Done/i }));
    expect(onCommit).toHaveBeenCalled();
  });

  it("Clear source removes source from output op", () => {
    renderPanel("problem");
    fireEvent.click(screen.getByRole("button", { name: /clear source/i }));
    expect(screen.getByLabelText(/source/i)).toHaveValue("");
  });
});
```

- [ ] **Step 2: Run (fail)**

Run: `bun run test -- src/components/videos/__tests__/StatPanel.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement `StatPanel`**

```tsx
// frontend/src/components/videos/drawer/panels/StatPanel.tsx
import { useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";
import type { Stat } from "../../types";

interface Props {
  path: string;
  onCommit: () => void;
  onCancel: () => void;
}

function resolveStat(spec: ReturnType<typeof useBeatEditor>["effectiveSpec"], path: string): Stat | null {
  if (path === "problem") return spec.problem ?? null;
  const m = /^impact\[(\d+)\]$/.exec(path);
  if (!m) return null;
  return spec.impact?.[parseInt(m[1], 10)] ?? null;
}

export function StatPanel({ path, onCommit, onCancel }: Props) {
  const { effectiveSpec, dispatch } = useBeatEditor();
  const initial = resolveStat(effectiveSpec, path);
  const [big, setBig] = useState(initial?.big ?? "");
  const [caption, setCaption] = useState(initial?.caption ?? "");
  const [source, setSource] = useState(initial?.source ?? "");

  if (!initial) return <div>(stat not found)</div>;

  const dirty =
    big !== initial.big ||
    caption !== initial.caption ||
    source !== (initial.source ?? "");

  const commit = () => {
    if (!dirty) return;
    const op: any = { op: "set-stat", path };
    if (big !== initial.big) op.big = big;
    if (caption !== initial.caption) op.caption = caption;
    if (source !== (initial.source ?? "")) op.source = source; // "" clears
    dispatch({ type: "APPEND_OP", op });
    onCommit();
  };

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Big</span>
        <input
          aria-label="big"
          value={big}
          onChange={(e) => setBig(e.target.value)}
          className="w-full rounded border bg-background p-2 text-2xl font-bold"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Caption</span>
        <textarea
          aria-label="caption"
          value={caption}
          onChange={(e) => setCaption(e.target.value)}
          rows={2}
          className="w-full rounded border bg-background p-2 text-sm"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Source (optional)</span>
        <div className="flex gap-2">
          <input
            aria-label="source"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className="flex-1 rounded border bg-background p-2 text-sm"
          />
          <button type="button" onClick={() => setSource("")}
                  className="rounded border px-2 py-1 text-xs">
            Clear source
          </button>
        </div>
      </label>
      <div className="mt-2 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="rounded border px-3 py-1.5 text-sm">
          Cancel
        </button>
        <button type="button" onClick={commit} disabled={!dirty}
                className="rounded bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          Done
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `bun run test -- src/components/videos/__tests__/StatPanel.test.tsx`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/videos/drawer/panels/StatPanel.tsx \
        frontend/src/components/videos/__tests__/StatPanel.test.tsx
git commit -m "videos(editor): StatPanel with big/caption/source + clear-source"
```

---

## Phase F — Save flow

### Task 21: `<BeatEditorTopBar>` with Save / Discard

**Files:**
- Modify: `frontend/src/components/videos/BeatEditorTopBar.tsx`

- [ ] **Step 1: Implement**

```tsx
// frontend/src/components/videos/BeatEditorTopBar.tsx
import { useState } from "react";
import { useBeatEditor } from "./BeatEditorContext";
import { submitEditBatch, getVideoRun } from "@/api/videos";
import type { ProgramSpec } from "./types";

interface Props {
  onSpecRefetched?: (s: ProgramSpec) => void;
}

export function BeatEditorTopBar({ onSpecRefetched }: Props) {
  const { state, dispatch, workspaceSlug, programSlug, runId } = useBeatEditor();
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  const dirty = state.buffer.length > 0;
  const status = state.saveState.status;

  const onSave = async () => {
    if (!dirty || status === "saving") return;
    dispatch({ type: "SAVE_START" });
    try {
      await submitEditBatch(workspaceSlug, programSlug, runId, state.buffer);
      // Refetch the canonical spec so effectiveSpec re-derives from server truth.
      const fresh = await getVideoRun(workspaceSlug, programSlug, runId);
      if (fresh.spec) {
        dispatch({ type: "REPLACE_SPEC", spec: fresh.spec });
        onSpecRefetched?.(fresh.spec);
      } else {
        dispatch({ type: "CLEAR_BUFFER" });
      }
      dispatch({ type: "SAVE_OK", at: Date.now() });
    } catch (e: unknown) {
      dispatch({ type: "SAVE_ERROR", message: e instanceof Error ? e.message : String(e) });
    }
  };

  const onDiscard = () => {
    if (!confirmDiscard) {
      setConfirmDiscard(true);
      setTimeout(() => setConfirmDiscard(false), 3000);
      return;
    }
    dispatch({ type: "CLEAR_BUFFER" });
    setConfirmDiscard(false);
  };

  let label: string;
  if (status === "saving") label = "Saving…";
  else if (status === "error") label = `⚠ Save failed: ${(state.saveState as any).message}`;
  else if (status === "saved" && !dirty)
    label = `✓ Saved at ${new Date((state.saveState as any).at).toLocaleTimeString()}`;
  else if (dirty) label = `${state.buffer.length} edit${state.buffer.length === 1 ? "" : "s"} pending`;
  else label = "No unsaved changes";

  return (
    <div className="sticky top-0 z-30 flex items-center gap-3 rounded-md border bg-background p-3 shadow-sm">
      <div className={dirty ? "text-sm font-medium text-amber-700" : "text-sm text-muted-foreground"}>
        {label}
      </div>
      {dirty && (
        <>
          <button
            type="button"
            onClick={onSave}
            disabled={status === "saving"}
            className="ml-auto rounded bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            Save changes
          </button>
          <button
            type="button"
            onClick={onDiscard}
            className="rounded border px-3 py-1.5 text-sm"
          >
            {confirmDiscard ? "Click again to confirm" : "Discard all"}
          </button>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type check + manual verify**

```bash
bunx tsc -b --noEmit
```

End-to-end manual check (with flag on):
1. Click a clip → trim drag → Done → BeatCard shows "edited" pill, TopBar shows "1 edit pending"
2. Click Save → POST hits `/edit-batch`, TopBar shows "Saved at HH:MM"
3. Reload page → edit persists in YAML

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/videos/BeatEditorTopBar.tsx
git commit -m "videos(editor): BeatEditorTopBar wires Save+Discard to /edit-batch"
```

---

### Task 22: Integration test for `<BeatEditor>`

**Files:**
- Create: `frontend/src/components/videos/__tests__/BeatEditor.test.tsx`

- [ ] **Step 1: Write the test**

Create `frontend/src/components/videos/__tests__/BeatEditor.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { BeatEditor } from "../BeatEditor";
import type { ProgramSpec } from "../types";
import * as api from "@/api/videos";

const spec: ProgramSpec = {
  slug: "demo", name: "Demo",
  narration: { by_beat: { hook: "Initial" } },
  beats: [
    { id: "hook", kind: "intro_hook", seconds: 4 },
  ],
};

describe("BeatEditor integration", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("edit → save flow clears buffer", async () => {
    const submit = vi.spyOn(api, "submitEditBatch").mockResolvedValue({
      ok: true, applied: 1, message: "ok",
    });
    vi.spyOn(api, "getVideoRun").mockResolvedValue({
      program_slug: "demo", run_id: "run-001", name: "Demo",
      manifest_count: 0, has_output: false, has_explorer_build: false,
      explorer_url: "", yaml_path: "",
      spec: { ...spec, narration: { by_beat: { hook: "Updated" } } },
    } as any);

    render(
      <BeatEditor
        workspaceSlug="ws1" programSlug="demo" runId="run-001" spec={spec}
      />,
    );

    // Click narration widget → drawer opens
    fireEvent.click(screen.getByText(/Initial/));
    const ta = await screen.findByRole("textbox");
    fireEvent.change(ta, { target: { value: "Updated" } });
    fireEvent.click(screen.getByRole("button", { name: /Done/i }));

    // TopBar shows 1 pending
    expect(screen.getByText(/1 edit pending/i)).toBeInTheDocument();

    // Save
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }));
    await waitFor(() => expect(submit).toHaveBeenCalled());
    const args = submit.mock.calls[0];
    expect(args[0]).toBe("ws1");
    expect(args[1]).toBe("demo");
    expect(args[3]).toEqual([
      { op: "set-narration", beatId: "hook", text: "Updated" },
    ]);

    // Saved label appears
    await waitFor(() => expect(screen.getByText(/Saved at/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run**

Run: `bun run test -- src/components/videos/__tests__/BeatEditor.test.tsx`
Expected: PASS

- [ ] **Step 3: Run the full editor test suite**

Run: `bun run test -- src/components/videos`
Expected: all suites PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/videos/__tests__/BeatEditor.test.tsx
git commit -m "videos(editor): integration test for edit → save → buffer clear flow"
```

---

## Phase G — Wire-up and rollout

### Task 23: Enable the flag for dev + document

**Files:**
- Modify: `config/settings/development.py` (or wherever dev defaults live)
- Modify: `CLAUDE.md`

- [ ] **Step 1: Default the flag to True in development**

In `config/settings/development.py`, add (or override):

```python
ACE_VIDEO_BEAT_EDITOR_REACT = True
```

Production stays `False` until we've dogfooded.

- [ ] **Step 2: Add a CLAUDE.md note**

In `CLAUDE.md`, under "Key architectural decisions" or near the videos section, add a bullet:

```markdown
- **Videos beat editor (React rewrite)**: as of 2026-05-15, the per-run editor
  is a native React tree under `frontend/src/components/videos/`
  (`<BeatEditor>` + reducer + drawer). Local-buffer dirty state, batched save
  via `POST /edit-batch`. Gated on `ACE_VIDEO_BEAT_EDITOR_REACT` (default
  False in prod until dogfooded). When False, falls back to the iframe-served
  HTML from `build-clip-explorer.ts`. Spec:
  `docs/specs/2026-05-15-video-beat-editor-react-port-design.md`.
```

- [ ] **Step 3: Run full backend + frontend test suites**

```bash
pytest apps/videos/ -v
bun run test -- src/components/videos
```
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add config/settings/development.py CLAUDE.md
git commit -m "videos(editor): enable React editor in dev + document"
```

---

### Task 24: Open PR

- [ ] **Step 1: Confirm branch state**

```bash
git status
git log --oneline main..HEAD
```

- [ ] **Step 2: Push and open PR**

```bash
git push -u origin HEAD
gh pr create --title "Video beat editor: React rewrite (Phase 1)" --body "$(cat <<'EOF'
## Summary

Replaces the iframe-served HTML beat editor with a native React surface
behind `ACE_VIDEO_BEAT_EDITOR_REACT` (default off in prod, on in dev).

- Local-buffer dirty state with coalescing-by-target append
- Top-level Save POSTs to new `POST /edit-batch` (one Drive round-trip)
- Click-to-edit drawer (modal shell available behind one-line swap)
- Trim widget reimplemented: window-level pointer listeners, non-overlapping
  hit areas, keyboard nudge, numeric inputs
- Stats (`problem`, `impact[]`) now editable via new `set-stat` op
- `build-clip-explorer.ts` untouched (still powers the share artifact)

Spec: `docs/specs/2026-05-15-video-beat-editor-react-port-design.md`
Plan: `docs/plans/2026-05-15-video-beat-editor-react-rewrite.md`

## Test plan

- [ ] `pytest apps/videos/` green
- [ ] `bun run test -- src/components/videos` green
- [ ] Dev: flag on → React editor renders; flag off → iframe renders
- [ ] Edit a clip trim → Save → reload page → trim persists
- [ ] Edit narration → Save → reload page → narration persists
- [ ] Edit a stat → Save → reload page → stat persists
- [ ] Click Re-render → background render still works against the new YAML
- [ ] Drag trim handle fast across the entire bar — no mid-drag capture loss

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Verify PR URL surfaces and CI starts**

Watch the PR page; ensure backend + frontend + Schemathesis CI all green.

---

## Self-review checklist

Run through this after the last task ships:

1. **Spec coverage** — Every section of `docs/specs/2026-05-15-video-beat-editor-react-port-design.md` has a corresponding task:
   - Architecture (component tree, state model, data flow) → Tasks 6, 7, 10, 14, 21
   - API `/edit-batch` → Tasks 1, 4, 5
   - `set-stat` op → Tasks 1, 3
   - Trim widget fixes → Task 17
   - DrawerShell + ModalShell swappable → Task 16
   - Per-widget UX (clip, narration, stats, brand) → Tasks 14, 15, 18, 19, 20
   - Feature flag rollout → Tasks 11, 23
   - Tests (reducer, applyOps, TrimBar, NarrationPanel, StatPanel, BeatEditor integration) → Tasks 6, 7, 17, 19, 20, 22
   - Error handling (save fail keeps buffer, discard, drawer ESC close) → Tasks 16, 21
   - Coalescing → Task 7

2. **Placeholder scan** — no TBDs, no "add error handling", no "fill in tests" — every step has the actual code or actual command.

3. **Type consistency** — `PendingChange` shape matches between `types.ts`, `applyOps.ts`, `editorReducer.ts`, `api/videos.ts (EditBatchOp)`, and the backend `ClipEditIn` op literal.

4. **Ambiguity** — `path` for `set-stat` uses the same `"problem" | "impact[N]"` string format on both sides; coalescing key strings are deterministic; the `source: ""` semantics is explicit (clears) in both backend and frontend.
