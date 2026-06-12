# Template Editor — Design Spec

**Date:** 2026-06-08
**Status:** Approved design, pre-plan
**Surfaces:** `videos/templates` (gallery) + `videos/templates/:templateId` (editor)
**Related:** `apps/videos/templates.py`, `apps/videos/api.py`, `frontend/src/components/videos/`, `frontend/src/components/workbench/`

---

## 1. North star

A comprehensive, browser-based editor for the **video-spec templates** we author
(`connect-explainer`, `program-designer`, `partnership-pitch`, `60s-campaign-overview`, …),
editable **live on the deployed labs app** — so we can "go through what we built
together," tune the templates, and improve them in the same loop we use for videos.

The editor is **as rich as the current video BeatEditor**: it edits everything
relevant about a template's YAML through structured panels, not raw text fields.

## 2. What a "template" is (and where it lives)

A template today is a directory `video-production/connect-videos/templates/<id>/`:

| File | Role | Runtime-read? |
|------|------|---------------|
| `template.yaml` | metadata (name, description, duration, audience, when_to_use) | ✅ (`templates.py` → picker + bundle) |
| `spec.template.yaml` | spec **skeleton** with `{{placeholders}}` | ✅ (bundle → agent authoring) |
| `generate.prompt.md` | LLM authoring instructions | ✅ (bundle) |
| `example.spec.yaml` | a fully-filled **demo** spec | ❌ — **CI test fixtures only** (vitest `example-spec.test.ts`) |

**Key fact (verified):** nothing in `apps/` reads `example.spec.yaml` at runtime —
it is consumed only by the connect-videos vitest suite. So only three artifacts
(meta + skeleton + prompt) are runtime-relevant.

### Storage: Drive-backed, repo = seed

To make templates editable on labs they move to **per-workspace Drive**, under
`<workspace.drive_root>/videos/_templates/<id>/`:

```
videos/_templates/<id>/
  meta.yaml        # was template.yaml
  skeleton.yaml    # was spec.template.yaml
  prompt.md        # was generate.prompt.md
  example.spec.yaml  # the editable demo (see §5)
```

- Consistent with the videos module's "**Drive is source of truth, no ORM
  tables**" principle.
- The repo `templates/<id>/` keeps two jobs: (a) the **seed** that bootstraps each
  workspace's Drive copy, and (b) the **CI test fixtures** — `example.spec.yaml` +
  the example-spec vitest tests stay in the repo **unchanged** (the renderer's
  contract). Runtime source-of-truth = Drive; repo = starting seed + renderer
  contract. Same split-resolution the founding workspace seed already uses
  (`ACE_DRIVE_ROOT_FOLDER_ID` seeds once, then isn't runtime-read).
- **Per-workspace** (each workspace gets its own editable copy) — tenancy
  consistency with every other videos/opps read.

*(A DB-backed `Template` model was the alternative — transactional, faster — but it
breaks the no-ORM-tables principle. Rejected.)*

## 3. Backend

### 3.1 Drive-backed read-through (`templates.py`)
- Swap filesystem reads (`_templates_dir()` under `ACE_VIDEOS_ROOT`) → Drive
  read-through, **preserving the `TemplateMeta` / `TemplateBundle` dataclasses** so
  the MCP-exposed `GET /templates` and `GET /templates/{id}` contracts are unchanged.
- Cache long-lived (templates change rarely); invalidate via the existing videos
  `drive_changes` feed (separate Redis pageToken). Mirrors the `OppSnapshot`/spec
  cache pattern (`opp-cache-architecture.md`).
- `is_valid_template_id` slug-guard stays (mandatory before any Drive path build).

### 3.2 Seeding (`videos_seed_templates` management command)
- Idempotent: for a workspace, if `videos/_templates/` is missing/empty, upload the
  repo `templates/<id>/` tree (renaming to `meta.yaml`/`skeleton.yaml`/`prompt.md`,
  plus `example.spec.yaml`). Mirrors `videos_migrate_to_drive`.
- **Lazy auto-seed:** the first `list_templates()` for a workspace whose
  `_templates/` is empty seeds it transparently, so a fresh workspace shows the
  templates without a manual step.

### 3.3 Edit API
- **`PATCH /api/w/{slug}/videos/templates/{id}`** — body carries any subset of
  `{meta, skeleton_yaml, prompt_md, example_yaml}`. Validates: `skeleton_yaml` and
  `example_yaml` parse as YAML mappings; `meta` against the `TemplateMeta` shape;
  `example_yaml` additionally validates against the program-spec schema (so a saved
  demo always renders). All-or-nothing; writes changed files to Drive; invalidates
  cache. Returns the refreshed bundle.
- `GET /api/w/{slug}/videos/templates/{id}/example` — the editable demo spec (the
  bundle endpoint already returns meta+skeleton+prompt; the example is fetched here
  so the BeatEditor can load it).
- **No create/delete in v1** (edit existing only). Net-new templates are still a
  repo PR (they ship renderer-contract test fixtures).

## 4. Frontend surface

A **separate surface on the shared `WorkbenchLayout` kit** (not a tab on the
per-program video workbench — templates are a *sibling* to programs, not a property
of one program/run). Routes mirror the program routes:

- **`videos/templates`** — gallery. The `WorkbenchRail` lists templates; the main
  pane shows cards (name, description, duration, beat list, "edit" CTA).
- **`videos/templates/:templateId`** — the editor on `WorkbenchLayout`, rail
  navigating between templates.

### 4.1 Comprehensive structured editor (reuse the BeatEditor)
"Edit everything relevant about the YAML, just like the current video editor." The
editor is organized into structured sections, **reusing the existing
`components/videos/` panels** wherever the content is spec-shaped:

| Section | Editor | Reuses |
|---------|--------|--------|
| **Metadata** | form: name, description, duration, intended_audience, when_to_use | new `TemplateMetaPanel` |
| **Demo / example** | the **full BeatEditor** on `example.spec.yaml` — beats, narration (variants), stats (problem/impact), clips, ai_build, prospect, active_cut | existing `BeatEditor` + reducer + drawer panels, unchanged |
| **Generate prompt** | markdown editor (textarea + preview) | new `TemplatePromptPanel` |
| **Skeleton** | YAML editor with placeholder awareness (read-mostly; advanced) | new `TemplateSkeletonPanel` |

The **demo/example is the heart** — editing it is literally editing a spec, so the
BeatEditor and all its structured panels apply directly. Metadata + prompt round it
out; the skeleton is the advanced/raw artifact (the `{{placeholder}}` shape can't go
through the value-expecting BeatEditor, so it gets a guarded YAML editor).

### 4.2 Save semantics
Local-buffer dirty state with batched save (mirrors the BeatEditor's
`POST /edit-batch` coalescing): edits accumulate, **Save** issues a single
`PATCH /templates/{id}` (meta + prompt + skeleton) and, for the demo, the existing
example-spec save path. All-or-nothing.

## 5. The example demo

The `example.spec.yaml` becomes an editable Drive artifact (§2) so the demo can be
tuned in the BeatEditor inside the template surface. It remains **mirrored in the
repo** as the renderer-contract CI fixture; a future check can diff repo-seed vs
Drive-live to flag drift, but v1 simply lets Drive diverge (the repo copy is the
"as-seeded" baseline). Rendering the demo reuses the program render path (the
template's example is just a spec).

## 6. Phasing

1. **Backend Drive-backing + seed + read-through** — `templates.py` reads Drive;
   `videos_seed_templates` + lazy auto-seed; existing `GET` endpoints stay green.
2. **`PATCH` edit endpoint** + `GET …/example`.
3. **Frontend gallery** (`videos/templates`).
4. **Frontend editor** — metadata + prompt + skeleton panels + the BeatEditor demo,
   batched save.

## 7. Testing & guardrails

- **pytest:** Drive-backed `templates.py` read-through (seed → list → bundle →
  patch → re-read), validation rejects (bad YAML, schema-invalid example), cache
  invalidation, per-workspace isolation (a patch in one workspace doesn't leak).
- **vitest:** the existing `example-spec.test.ts` / `program-designer-spec.test.ts`
  stay (repo fixtures, renderer contract) — **unchanged**. New frontend tests for
  the template editor panels + batched save reducer (mirror the BeatEditor tests).
- **Slug validation** before any Drive path build (existing `is_valid_template_id`).
- **`scripts/qa/labs_probe.py`** gains the templates surface.
- Keep connect-videos CI (tsc + vitest + bundle) green; the repo `templates/`
  example fixtures are untouched.

## 8. Open / deferred

- Template **create/delete** in the UI (v1: edit-only; new templates are repo PRs).
- Repo-seed ↔ Drive-live **drift detection** (v1: Drive diverges freely).
- Promoting a Drive-edited template **back to the repo** (a future "export to PR").
