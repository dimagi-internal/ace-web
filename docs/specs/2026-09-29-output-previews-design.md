# Output previews, and the Phases screen's per-phase rail

**Status:** shipped (2026-09-29). ace-web half in this repo; plugin half in
`dimagi-internal/ace` (#2555).

## Why

The Phases screen listed everything a run built as a strip of chips across the
top, detached from the phase that built it. The Flow rail — what each step takes
in and hands on — existed only inside replay. And an output like the Learn app
or a labs dashboard opened with no picture of what it looks like, even though
ACE already takes screenshots of both:

* Phase 6 `app-screenshot-capture` walks the Learn and Deliver apps on the
  emulator and uploads a PNG per step, to `6-qa-and-training/screenshots/`.
* Phase 7's DDD render captures a screenshot per scene over the labs dashboards,
  but they go to canopy's DDD package, not the run folder.

Filed under Phase 6, the app screenshots sit two phases away from the apps they
show. A reader looking at Phase 3 ("here are the apps") sees nothing.

## What

1. **A preview belongs to the output, and lives with the phase that built the
   output** — whoever captured it. Phase 6 writes the app screenshots into
   Phase 3's folder.
2. **The right rail is always on**, scoped to the selected phase: what the phase
   built (with previews) on top, then each step's inputs and outputs. Replay
   keeps its growing step-by-step chain. The top strip goes.

## The contract (v1)

```
<run>/<N>-<phase-folder>/previews/<output-slug>/_previews.yaml
<run>/<N>-<phase-folder>/previews/<output-slug>/<NN>-<step>.png
```

* `<phase-folder>` is the folder of the phase that BUILT the output (from
  `lib/artifact-manifest.ts` `PHASES[].folder`, e.g. `3-commcare`), not the
  phase that captured the preview.
* `<output-slug>` is the output's key under `phases.<phase>.products` with every
  run of non-`[a-z0-9]` characters replaced by `-` (`apps.learn` → `apps-learn`,
  `synthetic.workflows.programme_report` → `synthetic-workflows-programme-report`).
* `_previews.yaml` is the index. It is stored as real YAML bytes
  (`drive_upload_binary`, `text/yaml`) — **never a Google Doc**, whose export
  mangles newlines (`skills/_training-template.md`).

```yaml
schema_version: 1
phase: commcare-setup              # run_state phase key that owns the output
output_key: apps.learn             # dotted key under phases.<phase>.products
captured_by: app-screenshot-capture   # the skill that took these
captured_phase: qa-and-training
captured_at: 2026-09-29T12:00:00Z
items:                             # display order
  - file_id: <drive id>
    name: 01-home.png
    caption: "Learn app home — three training modules listed"   # optional
```

Rules:

* **The index is authoritative.** A reader shows exactly `items`, in order.
  Only frames from a passing journey go in (the existing hard rule in
  `app-screenshot-capture` § Step 5); duplicates (`duplicate_of`) are left out.
* **Re-capture replaces.** A writer trashes the output folder's previous
  contents before writing new ones, so two builds' screenshots never mix.
* **One writer per output folder.** Different outputs never share an index, so
  no read-modify-write races.
* **`captured_by` is load-bearing for replay.** The files sit in Phase 3 but
  were made in Phase 6; the replay reveals them at `captured_by`'s step, never
  earlier.
* Nothing goes under `phases.<phase>.products` for previews. A mapping with a
  `file_id` there is itself read as an output by ace-web, so an index pointer in
  products would show up as a bogus "output".

A reader MAY also accept a previews folder with images but no index (shown in
name order, `captured_by` unknown → revealed with the output itself).

### Writers (plugin)

| Output | Folder | Writer |
|---|---|---|
| Learn / Deliver app | `3-commcare/previews/<app key>/` | `app-screenshot-capture` (Phase 6) |
| Labs dashboards / reports | `7-synthetic/previews/<dashboard key>/` | Phase 7 write-back, from the DDD render's per-scene screenshots (one or two frames per dashboard) |

`app-screenshot-capture`'s own manifest
(`6-qa-and-training/app-screenshot-capture_manifest.yaml`) stays where it is and
keeps listing every frame by `file_id`; its training consumers read by id, so
moving the PNGs does not affect them. `drive_path` in the manifest changes.

### Reader (ace-web)

* `apps/opps/output_previews.py` finds `previews/*/_previews.yaml` in the run
  tree listing the snapshot loader already makes (cached; no extra walk), reads
  each index, and attaches `previews[]` to the matching product
  (`phase` + `output_key`, or any key the product absorbed during
  de-duplication).
* **Legacy runs** (no previews folder): the Phase 6 capture manifest is read and
  its frames attached to the Learn / Deliver app by the manifest's own
  `journeys[].app` (rows cite a journey by `journey_id` or by `journey`, its
  recipe base), else by the journey's name (`journey-learn-*`). Checked against
  `bednet-check-2-visit`: 20260907-1126 → 35 / 28 frames (the manifest's own
  `distinct_frames`), 20260908-1544 → 32 / 23. It stops mattering as runs move
  to v1.
* Freshness: index files are tracked file ids, so an edit invalidates the cached
  snapshot; a NEW index lands with Phase 6's `run_state.yaml` write-back, which
  also invalidates it.
* Forks: `previews/` is not in the fork's skipped media subtrees, so a fork that
  carries Phase 3 carries its app previews — correct, since they show the same
  apps.

## Rail

* `GET /api/w/{ws}/opps/{slug}/runs/{run}/flow` → `{flow}` — the declared
  input/output map (`replay.build_flow`) without the replay timeline.
* Outside replay: the rail shows the selected phase — **Built in this phase**
  (each output with its preview thumbnails; click opens the viewer), then one
  card per step with its inputs (↑ jumps to the phase that made one) and
  outputs.
* In replay: the chain as before; each step card also lists the outputs it
  produced, and previews appear at `captured_by`'s beat.

## Addendum (2026-09-30): every output is a doc or has screenshots

**Rule.** Every output ace-web lists is either a file the in-page viewer draws
(a Doc, deck, sheet, PDF, image, video) or has one or more good screenshots.
Before this, only the apps (Phase 6's emulator walk) and — best effort — the
labs dashboards (Phase 7's render) had any. The Connect program and
opportunity, the chatbot, the solicitation, the demo-walkthrough package, the
labs reports and any Drive file the viewer cannot draw had nothing.

### ace-web: the gap list is the source of truth

`GET /api/w/{ws}/opps/{slug}/runs/{run_id}/preview-gaps` →

```json
{
  "run_id": "20260908-1544",
  "outputs": [
    {
      "id": "connect-setup:connect.opportunity",
      "phase": "connect-setup",
      "output_key": "connect.opportunity",
      "kind": "connect_opportunity",
      "title": "…",
      "url": "https://connect.dimagi.com/a/…/opportunity/…/",
      "file_id": null,
      "reason": "no-preview",
      "auth": "connect"
    }
  ],
  "covered": 14
}
```

* An output is a **gap** unless it is an in-page doc (a Drive file whose MIME
  the viewer draws) or already has ≥1 preview. `reason` is `no-preview`, or
  `not-viewable-file` for a Drive file the viewer cannot draw.
* `output_key` is exactly the key ace-web matches an index on, so a writer
  never re-derives ace-web's product walk.
* `auth` says which signed-in session can open `url`: `connect`
  (connect.dimagi.com), `labs` (labs.connect.dimagi.com, including canopy's
  `/canopy/` pages), `hq` (commcarehq.org), `ocs` (openchatstudio.com),
  `google` (a Drive file — use the Drive thumbnail/export, not a browser), or
  `public`.
* Empty `outputs` ⇒ the run meets the rule.

### Plugin: one capture skill, run at every phase end

A utility skill (not a run_state step — like `decisions-render`) that reads the
gap list for the current run, filtered to one phase or to all, and for each gap
opens `url` with the session `auth` names, captures one or more screenshots,
**looks at each one** and rejects a login page, an error, a 404 or a blank
page, then writes `<phase-folder>/previews/<slug of output_key>/` + its index
(`captured_by: output-preview-capture`, `captured_phase: <the phase it ran in>`).
Called at the end of Phases 3–8 and once at the end of the run to catch
anything left. What makes a GOOD screenshot per kind:

| Kind | Screenshot(s) |
|---|---|
| Connect program / opportunity | its page on Connect, top of page; the opportunity also its payment-units / verification section |
| Chatbot | the public chat with one real question answered (from the Phase 5 test suite), not the admin page |
| Solicitation | the public solicitation page |
| Labs dashboard / report | the rendered report with data loaded (not the spinner) |
| Demo-walkthrough package | the canopy package page (hero + narrative) |
| CommCare app (fallback when the emulator walk left none) | the HQ app's form summary |
| Drive file the viewer cannot draw | Drive's thumbnail, or a rendered first page |

### Replay

`captured_by` is a utility skill with no step of its own, so ace-web reveals a
preview at its capturer's step if the run has one, else at the end of
`captured_phase` — never before the output itself.
