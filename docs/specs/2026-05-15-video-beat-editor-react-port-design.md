# Video Beat Editor — React Rewrite (Phase 1)

**Status:** Design · 2026-05-15
**Scope:** Replace the iframe-served HTML beat editor with a native React surface. Click-to-edit drawer model, local-buffer dirty state, batched save. Fix trim-widget mouse bugs. Expand editable surface to stats panels.
**Out of scope (deferred):** Insert / remove beats, smart-regen, trim driving beat duration, library picker redesign, brand-template / voice / music-bed editor, `build-clip-explorer.ts` migration.

## Background

`apps/videos/` orchestrates per-program video runs. The current editor is a 1,500-line script (`video-production/connect-videos/scripts/build-clip-explorer.ts`) that emits a self-contained HTML page per run. `frontend/src/pages/VideoExplorerPage.tsx` iframes that HTML and bolts a "Re-render" button on top.

Three problems with the current setup:

1. **Trim widget mouse handling is buggy.** Pointer listeners are attached to the 14px handle element. `setPointerCapture` should route events back, but on fast drags or hit-area edge cases, capture is lost mid-drag. Handle hit areas (`left:-7px; right:-7px`) also overlap the region's slide-window grab zone, so clicks near the edge route ambiguously.
2. **Edits hit the server in real-time.** Each trim save and narration save fires its own `POST /edit`, which loads-mutates-saves `spec.yaml` in Drive. For a multi-edit working session this is N Drive round-trips when one would do.
3. **Editable surface is partial.** Only clip slots and per-beat narration are editable. Stats panels (`problem.big`, `impact[].big`, captions, sources) are read-only — the operator has to hand-edit `spec.yaml`. Brand-template strings are read-only at the program level (correctly — they live in `_defaults.yaml`).

The framework calls these narrative units **beats**, with `BeatKind` enum values (`intro_hook`, `body_scene`, `body_product_beats`, etc.); the UI calls them **sections** for plain language (see comment at `build-clip-explorer.ts:111`). This spec uses "beat" for code/data and "section" reserved for future user-facing copy.

## Architecture

Outer `VideoExplorerPage` (page header, Re-render button, render-status banner) stays. The iframe is removed; in its place, a new `<BeatEditor>` subtree under `frontend/src/components/videos/`:

```
VideoExplorerPage  (existing — owns Re-render + status banner)
└── BeatEditor                       NEW · context provider for buffer/drawer
    ├── BeatEditorTopBar             NEW · "N edits pending · Save · Discard"
    ├── TimelineStrip                NEW · color bars w/ dirty highlights; click-to-jump
    ├── FinalVideoPlayer             NEW · plays output.mp4 via existing serve_media
    ├── BeatList
    │   └── BeatCard  (× N)          NEW · header + widget list + dirty pill
    │       ├── ClipSlotWidget       NEW · scene-clip, product-beat clips
    │       ├── NarrationWidget      NEW · per-beat voiceover line
    │       ├── StatsWidget          NEW · problem.big, impact[].big
    │       └── BrandTemplateWidget  NEW · read-only summary of brand strings
    └── EditDrawer                   NEW · DrawerShell wrapping kind-switched EditPanel
        └── EditPanel  (ClipTrim | Narration | Stat)
```

`DrawerShell` is a thin presentational wrapper. A `ModalShell` sibling exists from day one and is selected via a `mode` prop on `EditDrawer`, defaulting to `"drawer"`. Switching the whole editor to modal is a one-line change.

### State model

A single React reducer owns editor state:

```ts
type EditorState = {
  spec: ProgramSpec;              // canonical, loaded from server
  buffer: PendingChange[];        // unsaved edits, append-only per session
  drawerTarget: WidgetRef | null; // {kind, beatId, index?} or null
}

type PendingChange =
  | { op: "set-clip-trim";  kind: "scene-clip"|"product-beat"; index: number; start_seconds: number; duration_seconds: number }
  | { op: "set-clip-asset"; kind: "scene-clip"|"product-beat"; index: number; alias: string }
  | { op: "set-narration";  beatId: string; text: string }
  | { op: "set-stat";       path: "problem" | `impact[${number}]`; big?: string; caption?: string; source?: string };
```

**Derived state:** `effectiveSpec = applyOps(spec, buffer)`. Pure function. Memoized. All read-side components (BeatCard, widgets, TimelineStrip) read from `effectiveSpec`; the source `spec` is only re-fetched after a successful save.

**Buffer coalescing:** `APPEND_OP` is not literally append-only — it's "replace-or-append-by-target." When dispatching a new op, the reducer checks the buffer for an existing op with the same target (defined per op kind):

| Op | Same-target key |
|---|---|
| `set-clip-trim` | `(kind, index)` |
| `set-clip-asset` | `(kind, index)` |
| `set-narration` | `(beatId)` |
| `set-stat` | `(path)` |

If found, replace in place (preserves order); otherwise append. This keeps the buffer minimal — editing one clip's trim three times stays as one op, not three. The TopBar pending-count reflects unique targets edited.

Why this shape:
- Single source of truth for "what's pending" — no multi-state reconciliation
- Discard-all is one dispatch
- Future Undo support is additive (history stack alongside the buffer)
- Diff display ("trim @learn-cert: 0–3s → 1.2–4.3s") falls out of the op list directly

### Data flow — one edit cycle

1. User clicks a widget → context dispatches `OPEN_DRAWER({kind, beatId, index?})`
2. `EditDrawer` mounts `EditPanel` of the matching kind; panel reads initial values from `effectiveSpec`, holds a local draft
3. User edits (drags trim, types narration, etc.) → draft updates locally, no global re-render
4. Click **Done** → panel diffs draft vs effectiveSpec; if changed, dispatches `APPEND_OP(PendingChange)`; either way `CLOSE_DRAWER`
5. BeatCard for that beat re-renders with a dirty pill; TopBar increments count
6. Click **Save Changes** → POST `/edit-batch` → on 200, `CLEAR_BUFFER` + GET spec → toast "Saved · click Re-render to regenerate"

The "Re-render" button is unchanged — same call, same render-status polling, same busy banner.

## API

### New endpoint: `POST /edit-batch`

Path: `/api/w/<workspace_slug>/videos/programs/<program_slug>/runs/<run_id>/edit-batch`

Body:
```json
{ "ops": [ <PendingChange>, <PendingChange>, ... ] }
```

Behavior (in `apps/videos/service.py`):
- Refactor existing `apply_edit(workspace, slug, run_id, body)` into:
  - `_apply_single_op(doc, op) -> EditResult` — pure mutation on the loaded YAML doc
  - `apply_edit(...)` — load doc, apply one op, save (back-compat for existing `/edit` callers)
  - `apply_edit_batch(workspace, slug, run_id, ops) -> BatchResult` — load doc ONCE, apply all ops in order via `_apply_single_op`, save ONCE
- All-or-nothing: if any op fails validation, return 400 with the failing op index and message; doc is not saved
- Returns `{applied: N, message: str}`

Why batch:
- 5 edits → 1 Drive round-trip instead of 5
- Avoids partial-save inconsistency
- Single ruamel.yaml load/dump preserves comments without N times the parse work

The existing `/edit` endpoint stays unchanged (used by the `/ace:run` skill, scripted automation, the standalone share artifact).

### New op: `set-stat`

Currently `apply_edit` handles `set-clip-start`, `set-clip-trim`, `set-clip-asset`, `set-narration`. Add `set-stat`:

```python
if op["op"] == "set-stat":
    path = op["path"]  # "problem" | "impact[0]" | "impact[1]" | ...
    # Resolve path -> node in doc (problem or impact[i])
    # Patch `big`, `caption`, `source` fields present in op
    # Preserve fields not specified in op
```

Validation: `path` must match `^(problem|impact\[\d+\])$` and the index must be in range. `big`, `caption`, `source` are strings; absent fields are no-ops; explicit `null` for `source` deletes it.

### Endpoint reuse

`serve_media` (existing) streams source clip MP4s into React `<video>` tags by file name; works as-is. The `final.mp4` for `<FinalVideoPlayer>` uses the same endpoint with `file_name="final.mp4"`.

## Components

### `<BeatEditorTopBar>`

Sticky bar at the top of the editor area. Always visible.

- Idle state: "No unsaved changes"
- Dirty state: "N edit{s} pending · **Save Changes** · Discard all"
- Saving state: "Saving…"
- Saved state (~3s): "✓ Saved at HH:MM · click Re-render to regenerate"
- Error state: "⚠ Save failed: {message} · Retry · Discard"

Beat-level rollup: hovering "N edits pending" reveals a tooltip listing each pending op in human form ("trim @learn-cert · narration[hook] · stat problem").

### `<TimelineStrip>`

Same colored bar as today's iframe version. Per-beat segment with kind color + label. Dirty beats get an amber outline. Click jumps the `FinalVideoPlayer` to that beat's start and scrolls the matching `BeatCard` into view.

### `<BeatCard>` (visual contract)

```
┌──────────────────────────────────────────────────┐
│ ● Field footage · 0:15 → 0:22 · 7.0s   [● edited]│  ← header (kind dot, label, time window, dirty pill)
│ Real footage from the program location…          │  ← subtitle
├──────────────────────────────────────────────────┤
│ [NarrationWidget]                                │
│ [ClipSlotWidget × N]  OR  [StatsWidget × N]      │
│                       OR  [BrandTemplateWidget]  │
└──────────────────────────────────────────────────┘
```

Which widgets render depends on `BeatKind`. Mapping in `apps/videos/` is already encoded in `BeatBlock.assignments` logic — the React tree mirrors this with a kind-switch in `<BeatList>`.

### `<ClipSlotWidget>` (card)

- Header: alias chip (`@learn-cert`), status badge (✓ cached / ⚠ missing / literal), Drive open-link
- Body: 16:9 video thumbnail (poster frame from current trim IN-point)
- Footer: "X.Xs · A.As→B.Bs of source · final 0:22→0:25"
- Cursor: pointer; hover: outline + "Edit" hint
- Click → `OPEN_DRAWER({kind: "clip-trim", beatId, index})`

### `<ClipTrimPanel>` (drawer)

- Large source-clip `<video>` (live-seeks as trim region drags)
- New `<TrimBar>` (see Trim widget section below)
- Numeric inputs for `start_seconds` and `duration_seconds` (two decimals, ± buttons, keyboard arrows)
- "Swap clip" — opens an inline library picker (reuses today's library data; UI is read-only list with click-to-replace)
- Done / Cancel buttons

### `<NarrationWidget>` (card)

- Header: "Voiceover line"
- Body: prose paragraph, or "(no narration — click to add)" empty state
- Footer: word count + estimated read seconds (`chars / 15 ≈ s` heuristic)
- Click → `OPEN_DRAWER({kind: "narration", beatId})`

### `<NarrationPanel>` (drawer)

- Large textarea (auto-resize), word/char counter
- Estimated read time hint, with the beat's allotted seconds inline for comparison
- Voice + model info shown read-only ("Voice: Charlotte · Model: eleven_turbo_v2")
- Info note: "Identical text reuses the cached audio — no resynth on Re-render."
- Done / Cancel

### `<StatsWidget>` (card)

- For `body_problem_stat`: one card with `big`, `caption`, `source`
- For `body_impact_stats`: one card per `impact[]` entry
- Big number rendered large; caption + optional source line below
- Click → `OPEN_DRAWER({kind: "stat", path: "problem" | "impact[i]"})`

### `<StatPanel>` (drawer)

- `big` text input rendered at large size (visual preview of the on-screen treatment)
- `caption` multi-line input
- `source` single-line, optional (toggle to clear)
- Done / Cancel

### `<BrandTemplateWidget>` (card, read-only Phase 1)

- Lists what the beat renders from (cycle steps, hook tagline, CTA link)
- "Edit globally" link disabled with tooltip: "Brand strings live in `_defaults.yaml`. Per-program override coming in a future release."

### `<EditDrawer>` / `<DrawerShell>` / `<ModalShell>`

```
EditDrawer { mode: "drawer" | "modal", ... }
  ├── if mode==="drawer": <DrawerShell> mounts EditPanel as a right-sliding sheet
  └── if mode==="modal":  <ModalShell>  mounts EditPanel as a centered overlay
```

Both shells expose the same prop contract: `{open, title, onClose, children, footerActions}`. `EditPanel` is shell-agnostic.

Default: `"drawer"`. Override per-kind if a kind benefits from one mode over the other (e.g., clip-trim probably stays drawer; narration could go either way).

## Trim widget — concrete fixes

`<TrimBar>` reimplemented:

```ts
function TrimBar({ sourceDuration, start, duration, onChange }: Props) {
  const barRef = useRef<HTMLDivElement>(null);

  const startDrag = (mode: "left" | "right" | "move") => (e: React.PointerEvent) => {
    e.preventDefault();
    const barRect = barRef.current!.getBoundingClientRect();
    const startX = e.clientX;
    const initial = { start, duration };

    const onMove = (ev: PointerEvent) => {
      const dSec = ((ev.clientX - startX) / barRect.width) * sourceDuration;
      // ... compute new start/duration per mode, clamp, call onChange
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  // Handles rendered INSIDE the region — no negative offsets
  return (
    <div ref={barRef} className="trim-bar">
      <div className="trim-region" style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
           onPointerDown={startDrag("move")}>
        <div className="trim-handle trim-handle-left"  onPointerDown={startDrag("left")}  tabIndex={0} />
        <div className="trim-handle trim-handle-right" onPointerDown={startDrag("right")} tabIndex={0} />
      </div>
    </div>
  );
}
```

Fixes:
1. **Listeners on `window`.** Fast drags past the handle don't lose capture.
2. **Handles inside the region** (`left:0; width:14px` and `right:0; width:14px`, no negative offsets). The slide-window grab zone is the region's interior between the handles. Hit areas are disjoint.
3. **Keyboard support.** When a handle has focus, ←/→ nudge ±0.1s; shift+←/→ nudge ±1.0s.
4. **Numeric inputs in drawer.** For precision a slider can't give.

`ResizeObserver` on the bar is a belt-and-suspenders fallback for layout shifts mid-drag (drags are usually too short for it to fire, but it's free).

## Wire-up to existing surfaces

`VideoExplorerPage` keeps:
- `flushPending()` pattern at line 141 — *removed*; was the iframe→React bridge. React owns the buffer now.
- Re-render button + render-status polling — unchanged
- Workspace + program/run identifier resolution — unchanged

The page renders `<BeatEditor program={...} run={...} />` where the iframe used to mount.

`build-clip-explorer.ts` is **kept untouched**. It still emits the standalone HTML used by:
- Per-run share artifact uploaded to Drive
- `/opps/<slug>/summary` public page (if it embeds the explorer)

A later spec migrates or deprecates it. Phase 1 explicitly does not.

## Testing

Frontend (`bun run test`):
- `editorReducer.test.ts` — every `PendingChange` op, drawer open/close, discard all, save success path
- `applyOps.test.ts` — pure spec mutator: trim, asset swap, narration, stats
- `TrimBar.test.tsx` — drag via `fireEvent.pointerDown` / `pointerMove` / `pointerUp` on `window`; keyboard nudge; bounds clamping (start≥0, start+dur≤sourceDuration); region drag mode
- `NarrationPanel.test.tsx` — textarea Save, Cancel, dirty detection, ⌘+Enter shortcut
- `StatPanel.test.tsx` — field updates, source clear-toggle
- `BeatEditor.test.tsx` — integration: open drawer → edit → done → buffer increments; save → mocked POST `/edit-batch` succeeds → buffer clears, spec refetched

Backend (`pytest`):
- `test_apply_edit_batch.py` — empty ops, single op, mixed ops, invalid op (rejected without partial save), all-or-nothing on failure midway, YAML comment preservation through batch round-trip
- `test_set_stat.py` — `problem` path, `impact[i]` path, out-of-range index, clearing `source` via `null`
- Existing `/edit` tests stay (back-compat coverage)

## Error handling

- **Save fails (network/server):** keep buffer, surface error message inline in TopBar with Retry and Discard buttons. User can keep editing while in error state; Retry re-sends.
- **Save partial-fail (server validation):** Backend returns 400 with `{failed_index, message}`. UI surfaces "Edit #N failed: <message>" with a "Discard that edit" button; remaining edits stay in buffer for retry.
- **Spec drifted on server (someone else edited via `/ace:run`):** Out of scope. Phase 1 assumes single-editor sessions. A future spec could add ETag-based optimistic concurrency.
- **Drawer open with stale data after external refetch:** When `spec` is refetched (after Save), if drawer is open, close it and surface a "Spec reloaded — your edit was saved" toast. Drafts that weren't committed are lost; user is warned by Cancel-button copy in the drawer ("Cancel · drafts not yet committed will be lost").

## Migration / rollout

- Feature flag: `ACE_VIDEO_BEAT_EDITOR_REACT` (default `True` once shipped). When `False`, `VideoExplorerPage` falls back to the iframe.
- Both surfaces talk to the same `/edit` endpoint and same Drive YAML, so flipping back is safe per-session.
- After ~2 weeks of stability, remove the flag and the iframe code path.

## Open questions (none blocking)

None. The deferred items in "Out of scope" are explicit follow-up specs; everything in scope is decided.

## Follow-up specs (named for clarity, not committed)

- **Phase 2 · Insert / remove / reorder beats.** Per-program beat list overriding `_defaults.yaml`; library of insertable beat templates; renderer generalization.
- **Phase 3 · Smart-regen.** Diff-aware Re-render: detect which stages (asset hydrate, narration synth, captions, encode) can be skipped based on spec delta. Narration synth is already content-hash-cached; the encode is where the real wall-time lives.
- **Phase 4 · Trim drives duration.** Beat duration sums from clip slot durations (with constraint solver to keep total = `total_seconds`). Narration timing flexes correspondingly.
- **Phase 5 · Brand / voice / music editor.** Per-program override of `_defaults.yaml` strings + voice provider switching + music bed swap.
- **Phase 6 · `build-clip-explorer.ts` migration.** Either deprecate or regenerate from the React tree (SSR snapshot, MHTML, or simple link-to-workbench-read-only).
