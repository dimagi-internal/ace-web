# Template Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the video-spec templates Drive-backed and editable live on labs through a comprehensive structured editor (reusing the BeatEditor for the demo).

**Architecture:** Templates move from baked repo files to per-workspace Drive (`<ws>/videos/_templates/<id>/{meta.yaml,skeleton.yaml,prompt.md,example.spec.yaml}`), seeded from the repo. `templates.py` becomes a Drive read-through with cache; a `PATCH` endpoint writes edits back. A new `videos/templates` frontend surface on the shared `WorkbenchLayout` edits metadata + prompt + skeleton + the demo (via the existing BeatEditor). Repo `templates/` stays the seed + the connect-videos CI fixtures.

**Tech Stack:** Django + Ninja + Pydantic (backend), Drive client, Redis cache; React 19 + Vite + the existing `components/videos` + `components/workbench` kits (frontend); pytest + vitest.

**Spec:** `docs/specs/2026-06-08-template-editor-design.md`

---

## File Structure

**Backend (create/modify):**
- `apps/videos/drive.py` — add templates Drive helpers (mirror `program_folder_id`/`write_spec`).
- `apps/videos/templates.py` — Drive-backed loaders + seed + save (currently filesystem, workspace-agnostic).
- `apps/videos/cache.py` — add template cache keys.
- `apps/videos/management/commands/videos_seed_templates.py` — seed command.
- `apps/videos/api.py` — pass workspace to loaders; add `PATCH` + `GET …/example`.
- `apps/videos/schemas.py` — `TemplatePatchIn`, `TemplateExampleOut`.
- `apps/videos/tests/test_templates.py` — extend for Drive-backing + patch + isolation.

**Frontend (create/modify):**
- `frontend/src/api/videos.ts` — template client fns + generated types.
- `frontend/src/pages/TemplatesPage.tsx` — gallery.
- `frontend/src/pages/TemplateEditorPage.tsx` — editor on `WorkbenchLayout`.
- `frontend/src/components/videos/template/TemplateMetaPanel.tsx`
- `frontend/src/components/videos/template/TemplatePromptPanel.tsx`
- `frontend/src/components/videos/template/TemplateSkeletonPanel.tsx`
- `frontend/src/components/videos/template/templateEditorReducer.ts` — dirty-buffer + batched save (mirror `editorReducer.ts`).
- `frontend/src/router.tsx` — add routes.
- `frontend/src/components/videos/template/__tests__/*` — panel + reducer tests.

---

## Phase 1 — Backend: Drive-backed templates + seed

### Task 1: Templates Drive helpers

**Files:**
- Modify: `apps/videos/drive.py`
- Test: `apps/videos/tests/test_templates.py`

- [ ] **Step 1: Write failing test** (use the existing fake Drive client in `test_templates.py`/`conftest`; mirror how `test_service.py` fakes Drive).

```python
# apps/videos/tests/test_templates.py
def test_templates_folder_and_files_roundtrip(fake_workspace):
    from apps.videos import drive
    layout, client = service.layout_for(fake_workspace)
    tid = drive.templates_folder_id(layout, client, create=True)
    assert tid is not None
    fid = drive.write_template_file(layout, client, "demo", "meta.yaml", "name: Demo\n")
    assert fid is not None
    assert drive.read_template_file(layout, client, "demo", "meta.yaml") == "name: Demo\n"
    assert "demo" in drive.list_template_ids(layout, client)
```

- [ ] **Step 2: Run → FAIL** (`templates_folder_id` undefined): `.venv/bin/pytest apps/videos/tests/test_templates.py::test_templates_folder_and_files_roundtrip -v`

- [ ] **Step 3: Implement** in `drive.py` (mirror `program_folder_id`/`write_spec`/`_find_child`; `_TEMPLATES_FOLDER = "_templates"`):

```python
_TEMPLATES_FOLDER = "_templates"

def templates_folder_id(layout, client, *, create: bool = False) -> str | None:
    existing = _find_child(client, layout.videos_folder_id, _TEMPLATES_FOLDER)
    if existing is not None and existing.mime_type == "application/vnd.google-apps.folder":
        return existing.id
    if not create:
        return None
    return client.create_folder(layout.videos_folder_id, _TEMPLATES_FOLDER)

def _template_folder_id(layout, client, template_id: str, *, create: bool = False) -> str | None:
    root = templates_folder_id(layout, client, create=create)
    if root is None:
        return None
    existing = _find_child(client, root, template_id)
    if existing is not None and existing.mime_type == "application/vnd.google-apps.folder":
        return existing.id
    return client.create_folder(root, template_id) if create else None

def list_template_ids(layout, client) -> list[str]:
    root = templates_folder_id(layout, client)
    if root is None:
        return []
    return sorted(c.name for c in client.list_children(root)
                  if c.mime_type == "application/vnd.google-apps.folder")

def read_template_file(layout, client, template_id: str, name: str) -> str | None:
    fid = _template_folder_id(layout, client, template_id)
    if fid is None:
        return None
    child = _find_child(client, fid, name)
    return client.read_text(child.id) if child is not None else None

def write_template_file(layout, client, template_id: str, name: str, content: str) -> str:
    fid = _template_folder_id(layout, client, template_id, create=True)
    assert fid is not None
    existing = _find_child(client, fid, name)
    mime = "text/markdown" if name.endswith(".md") else YAML_MIME
    if existing is not None:
        client.update_file(existing.id, content, mime)
        return existing.id
    return client.upload_file(fid, name, content, mime)
```
> Verify the exact `DriveClient` method names against `drive.py` (`list_children`/`read_text`/`upload_file`/`update_file`) and adjust to the real signatures before running.

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat(videos): templates Drive helpers`.

### Task 2: Seed templates from repo → Drive

**Files:**
- Modify: `apps/videos/templates.py` (keep `_templates_dir()` as the **seed source**; keep `TemplateMeta`/`TemplateBundle`/`is_valid_template_id`/`_load_meta`/`_strip_leading_doc_comments`).
- Test: `apps/videos/tests/test_templates.py`

- [ ] **Step 1: Failing test:**

```python
def test_seed_templates_uploads_repo_tree(fake_workspace):
    n = templates.seed_templates(fake_workspace)
    assert n >= 3  # connect-explainer, program-designer, partnership-pitch
    layout, client = service.layout_for(fake_workspace)
    assert "program-designer" in drive.list_template_ids(layout, client)
    assert "active_cut" in (drive.read_template_file(layout, client,
        "program-designer", "skeleton.yaml") or "")
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement `seed_templates`** (reads repo dir via `_templates_dir()`, uploads renamed files; idempotent — skip ids already present):

```python
_FILE_MAP = {  # repo filename -> Drive filename
    "template.yaml": "meta.yaml",
    "spec.template.yaml": "skeleton.yaml",
    "generate.prompt.md": "prompt.md",
    "example.spec.yaml": "example.spec.yaml",
}

def seed_templates(workspace) -> int:
    from . import drive
    layout, client = _layout_for(workspace)  # see note
    existing = set(drive.list_template_ids(layout, client))
    root = _templates_dir()
    seeded = 0
    for entry in sorted(root.iterdir()) if root.exists() else []:
        if not entry.is_dir() or not is_valid_template_id(entry.name) or entry.name in existing:
            continue
        for repo_name, drive_name in _FILE_MAP.items():
            p = entry / repo_name
            if p.exists():
                drive.write_template_file(layout, client, entry.name, drive_name,
                                          p.read_text(encoding="utf-8"))
        seeded += 1
    return seeded
```
> `_layout_for` = import from `service.layout_for` lazily to avoid a circular import (service imports templates? check; if so, inline `drive.client_for_workspace` + build the layout as service does).

- [ ] **Step 4: Run → PASS.** **Step 5: Commit** `feat(videos): seed templates to Drive`.

### Task 3: Drive-backed `list_templates` / `load_template` (+ lazy auto-seed + cache)

**Files:** Modify `apps/videos/templates.py`, `apps/videos/cache.py`. Test: `test_templates.py`.

- [ ] **Step 1: Failing test:**

```python
def test_list_and_load_template_from_drive_autoseeds(fake_workspace):
    # No explicit seed call — lazy auto-seed on first list.
    metas = templates.list_templates(fake_workspace)
    ids = {m.id for m in metas}
    assert {"connect-explainer", "program-designer", "partnership-pitch"} <= ids
    bundle = templates.load_template(fake_workspace, "program-designer")
    assert bundle is not None
    assert "active_cut" in bundle.skeleton_yaml
    assert bundle.prompt_md.strip()
```

- [ ] **Step 2: Run → FAIL** (signatures still workspace-agnostic).
- [ ] **Step 3: Implement** — `list_templates(workspace)`/`load_template(workspace, id)` read Drive (`read_template_file`), lazy-seed when `list_template_ids` is empty, parse `meta.yaml` via existing `_load_meta`-style logic, strip doc comments on skeleton via existing `_strip_leading_doc_comments`. Add cache keys in `cache.py`:

```python
def _tpl_list_key(ws): return f"videos:tpl:list:{ws}"
def _tpl_bundle_key(ws, tid): return f"videos:tpl:{ws}:{tid}"
def get_tpl_list(ws): ...   # mirror get_slugs
def set_tpl_list(ws, v): ...
def get_tpl_bundle(ws, tid): ...
def set_tpl_bundle(ws, tid, v): ...
def invalidate_tpl(ws, tid=None): ...  # drop bundle (+ list)
```
Read-through: `load_template` checks cache → Drive → set cache.

- [ ] **Step 4: Run → PASS.** **Step 5: Commit** `feat(videos): Drive-backed template read-through + cache`.

### Task 4: `videos_seed_templates` management command

**Files:** Create `apps/videos/management/commands/videos_seed_templates.py`. Test: `test_templates.py`.

- [ ] **Step 1: Failing test** (call command, assert it seeds; mirror an existing command test):

```python
def test_seed_command(fake_workspace):
    from django.core.management import call_command
    call_command("videos_seed_templates", workspace=fake_workspace.slug)
    layout, client = service.layout_for(fake_workspace)
    assert drive.list_template_ids(layout, client)
```

- [ ] **Step 2: FAIL.** **Step 3: Implement** (mirror `videos_migrate_to_drive.py`: `--workspace` arg, resolve Workspace, call `templates.seed_templates`, print count; default = all workspaces).
- [ ] **Step 4: PASS.** **Step 5: Commit** `feat(videos): videos_seed_templates command`.

### Task 5: Wire endpoints to Drive loaders (keep `GET` contracts)

**Files:** Modify `apps/videos/api.py:168-195` (`list_video_templates`, `get_video_template`). Test: `apps/videos/tests/test_api.py`.

- [ ] **Step 1: Failing test** — `GET /api/w/<ws>/videos/templates` returns the seeded metas; `GET …/{id}` returns the bundle (extend existing API tests).
- [ ] **Step 2: FAIL** (still calls workspace-agnostic loaders).
- [ ] **Step 3: Implement** — pass `workspace` (the resolved one) into `templates.list_templates(workspace)` / `templates.load_template(workspace, template_id)`. Response shapes (`TemplateMetaOut`/`TemplateBundleOut`) unchanged.
- [ ] **Step 4: PASS** — run the full `test_api.py` + `test_templates.py`. **Step 5: Commit** `feat(videos): template endpoints read Drive`.

---

## Phase 2 — Backend: edit API

### Task 6: `PATCH /templates/{id}` + `GET …/example`

**Files:** Modify `apps/videos/templates.py` (`save_template`, `load_example`), `apps/videos/schemas.py`, `apps/videos/api.py`. Test: `test_templates.py`, `test_api.py`.

- [ ] **Step 1: Failing tests:**

```python
def test_save_template_persists_and_invalidates(fake_workspace):
    templates.list_templates(fake_workspace)  # seed
    templates.save_template(fake_workspace, "connect-explainer",
                            meta={"name": "Renamed Explainer"})
    b = templates.load_template(fake_workspace, "connect-explainer")
    assert b.meta.name == "Renamed Explainer"

def test_save_template_rejects_bad_skeleton(fake_workspace):
    templates.list_templates(fake_workspace)
    with pytest.raises(ValueError):
        templates.save_template(fake_workspace, "connect-explainer",
                                skeleton_yaml=": not yaml :")

def test_patch_endpoint(client_authed, fake_workspace):
    templates.list_templates(fake_workspace)
    r = client_authed.patch(
        f"/api/w/{fake_workspace.slug}/videos/templates/connect-explainer",
        json={"meta": {"description": "new desc"}})
    assert r.status_code == 200
    assert r.json()["meta"]["description"] == "new desc"
```

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implement:**
  - `schemas.py`:
    ```python
    class TemplateMetaPatch(StrictModel):
        name: str | None = None; description: str | None = None
        expected_duration_seconds: int | None = None
        intended_audience: str | None = None; when_to_use: str | None = None
    class TemplatePatchIn(StrictModel):
        meta: TemplateMetaPatch | None = None
        skeleton_yaml: str | None = None
        prompt_md: str | None = None
        example_yaml: str | None = None
    class TemplateExampleOut(StrictModel):
        template_id: str; example_yaml: str
    ```
  - `templates.save_template(workspace, id, *, meta=None, skeleton_yaml=None, prompt_md=None, example_yaml=None)`: validate (`skeleton_yaml`/`example_yaml` parse as mapping via `ruamel`; `example_yaml` additionally passes the program-spec validation already used by `service.create_program_from_spec` — factor that check or call a shared validator); merge meta into the existing `meta.yaml` (round-trip), write changed files via `drive.write_template_file`, `cache.invalidate_tpl(ws, id)`. Raise `ValueError` on invalid.
  - `templates.load_example(workspace, id)` → `read_template_file(..., "example.spec.yaml")`.
  - `api.py`: `@router.patch("/templates/{template_id}", response=TemplateBundleOut)` → resolve workspace, slug-guard, `try: save_template(...) except ValueError → ProblemError(400, TYPE_VALIDATION)`, return refreshed bundle. `@router.get("/templates/{template_id}/example", response=TemplateExampleOut, openapi_extra={"x-mcp-expose": True})`.
- [ ] **Step 4: PASS.** **Step 5: Commit** `feat(videos): template PATCH + example endpoints`.

---

## Phase 3 — Frontend: gallery surface

### Task 7: Template API client + types

**Files:** Modify `frontend/src/api/videos.ts`; regen `frontend/src/api/generated.ts` (run the openapi typegen the repo uses). Test: none (thin client).

- [ ] **Step 1:** Add `listTemplates(ws)`, `getTemplate(ws, id)`, `getTemplateExample(ws, id)`, `patchTemplate(ws, id, body)` mirroring the existing program client fns in `videos.ts`. Regenerate types from the updated OpenAPI schema (`.github/workflows/regen-openapi` flow). Commit `feat(videos): template api client`.

### Task 8: Routes + gallery page

**Files:** Modify `frontend/src/router.tsx` (add `videos/templates` + `videos/templates/:templateId`); Create `frontend/src/pages/TemplatesPage.tsx`. Test: `frontend/src/pages/__tests__/TemplatesPage.test.tsx`.

- [ ] **Step 1: Failing test** — render `TemplatesPage` with a mocked `listTemplates` returning 3 metas; assert the 3 names render and each links to `videos/templates/:id` (mirror `MediaLibraryPage.test.tsx`).
- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implement** — `TemplatesPage` uses `WorkbenchLayout` + `WorkbenchRail` (rail lists templates); main pane = cards (name, description, `expected_duration_seconds`, "Edit" link). Add routes to `router.tsx` (after the `videos/library` route).
- [ ] **Step 4: PASS.** **Step 5: Commit** `feat(videos): templates gallery surface`.

---

## Phase 4 — Frontend: comprehensive editor

### Task 9: Template editor reducer (dirty buffer + batched save)

**Files:** Create `frontend/src/components/videos/template/templateEditorReducer.ts`; Test: `__tests__/templateEditorReducer.test.ts`. Mirror `components/videos/editorReducer.ts` + `applyOps.ts`.

- [ ] **Step 1: Failing test** — dispatch `set-meta-field`, `set-prompt`, `set-skeleton`; assert dirty flags + that `buildPatch(state)` returns only changed fields (e.g. only `{meta:{description}}` when just the description changed).
- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implement** the reducer: state `{meta, promptMd, skeletonYaml, exampleYaml, dirty:Set}`, actions for each field, `buildPatch` emitting only dirty parts. Coalesce-by-target like the BeatEditor.
- [ ] **Step 4: PASS.** **Step 5: Commit** `feat(videos): template editor reducer`.

### Task 10: Meta + prompt + skeleton panels

**Files:** Create `TemplateMetaPanel.tsx`, `TemplatePromptPanel.tsx`, `TemplateSkeletonPanel.tsx`; Tests under `__tests__/`.

- [ ] **Step 1: Failing tests** — `TemplateMetaPanel` renders inputs bound to meta fields and fires `set-meta-field` on change; `TemplatePromptPanel` is a markdown textarea firing `set-prompt`; `TemplateSkeletonPanel` is a guarded YAML textarea firing `set-skeleton` and showing a parse-error hint on invalid YAML.
- [ ] **Step 2: FAIL.** **Step 3: Implement** the three panels (controlled inputs; reuse the drawer/panel styling from `components/videos/drawer/panels`).
- [ ] **Step 4: PASS.** **Step 5: Commit** `feat(videos): template meta/prompt/skeleton panels`.

### Task 11: TemplateEditorPage — assemble + demo via BeatEditor + save

**Files:** Create `frontend/src/pages/TemplateEditorPage.tsx`; Test: `__tests__/TemplateEditorPage.test.tsx`.

- [ ] **Step 1: Failing test** — render with mocked `getTemplate` + `getTemplateExample`; assert the meta/prompt/skeleton sections render, the BeatEditor mounts on the example, and clicking **Save** calls `patchTemplate` once with the coalesced patch (meta + prompt + skeleton + example).
- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implement** — `TemplateEditorPage` on `WorkbenchLayout`: loads bundle + example, drives `templateEditorReducer`, renders the 3 panels + the **existing `BeatEditor`** bound to `exampleYaml` (the example is a real spec), and a Save button → `patchTemplate(ws,id,buildPatch())` (example flows through as `example_yaml`). Rail navigates templates.
- [ ] **Step 4: PASS** — run `bun run test`. **Step 5: Commit** `feat(videos): template editor page`.

### Task 12: QA probe + docs

**Files:** Modify `scripts/qa/labs_probe.py` (walk `videos/templates` + open one editor); `docs/qa/e2e-probe.md`; a line in `CLAUDE.md` (videos section) noting Drive-backed templates.

- [ ] **Step 1:** Add the templates surface to the probe; note the editor in CLAUDE.md. **Step 2:** Run `.venv/bin/pytest` + `bun run test` + connect-videos `npm test` (the repo `example.spec.yaml` fixtures untouched → still green). **Step 3: Commit** `feat(videos): template editor QA probe + docs`.

---

## Self-Review notes
- **Spec coverage:** §2 storage → T1–T3; §3.1 read-through+cache → T3; §3.2 seed → T2/T4; §3.3 PATCH/example → T6; §4 surface → T7–T11; §4.1 panels+BeatEditor reuse → T9–T11; §5 example editable → T6/T11; §7 tests/probe → every task + T12. Covered.
- **Deferred (not in plan, per spec §8):** template create/delete UI, repo↔Drive drift detection, export-to-PR.
- **Verify-before-run flags:** exact `DriveClient` method names (T1), the program-spec validator reuse (T6), and the openapi typegen command (T7) must be checked against the live code before running each task.
