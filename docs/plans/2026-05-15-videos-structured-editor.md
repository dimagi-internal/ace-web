# Videos: Structured YAML Editor (follow-up plan)

**Status**: design sketch, not yet implemented.
**Owner**: TBD.
**Trigger**: requested in the same iteration that landed the
programs/runs storage model (PR #366 follow-up).

## What this replaces

The current `VideoExplorerPage` iframes the generated
`out/clip-explorer/<slug>/runs/<run-NNN>/explorer/index.html`. The iframe
is the inherited Node-built UI: a per-section card view with trim
handles, an inline contenteditable for narration, and a feedback
drawer. It works but it's two products glued at the iframe boundary —
the explorer's CSS, JS, and DOM model live in `build-clip-explorer.ts`,
not in React.

The end-state replaces the iframe with a **structured YAML editor**
rendered as native React. Each field in `spec.yaml` becomes an inline
editor, with the relevant media (video clip, voiceover MP3, music bed)
embedded right next to the field it backs. Save persists to the run's
spec.yaml via the existing `/edit` ops; render kicks off via `/build`.

## Why now

Three things make the iframe approach feel temporary:

1. **Theme parity is glued together via CSS variable overrides.** The
   dark-theme injection in `service.rewrite_explorer_html` works but
   isn't real. A native React surface inherits ace-web's tokens
   directly.
2. **The mental model is "edit the spec, see the render"**, but the
   iframe shows a derived view (timeline, sections, trim bars) with
   the spec hidden behind it. The user has asked for a YAML-first
   editor where fields are obvious and edits are atomic.
3. **Run iteration loop is fast.** With the programs/runs model, you
   want to: load a run → tweak one field → see exactly what changes →
   render → diff against the previous run. The iframe's per-section
   cards bury the field hierarchy; a native editor surfaces it.

## Out of scope

- Monaco / CodeMirror with raw YAML editing. The structured view is
  the affordance — operators want to *see* what they can change, not
  read raw YAML.
- Multi-user concurrent editing. Runs are mutable but assumed single-
  writer in practice (matches the rest of ace-web's local-dev model).
- A new "create program" wizard. Programs are still seeded by hand
  for now.

## Shape of the editor

Page layout (`/w/<ws>/videos/<program>/runs/<run>`):

```
┌──────────────────────────────────────────────────────────────────┐
│ TopNav  · All programs · CHC · Run: run-003 ▾ · Copy · Render  │ ← existing
├──────────────────────────────────────────────────────────────────┤
│ <video src="output.mp4" controls />  · 60s · 1.2 MB              │
├──────────────────────────────────────────────────────────────────┤
│ Sections (collapsible cards, ordered)                            │
│                                                                  │
│  ▾ Identity                                                      │
│      name:         Child Health Campaign      [edit]             │
│      tagline:      Door-to-door Vitamin A …   [edit]             │
│      country:      Kenya                      [edit]             │
│      program_url:  https://labs.connect…      [edit]             │
│                                                                  │
│  ▾ Scene (intro b-roll)                                          │
│      clip [0]: @field-group-around-woman    ▶ [video preview]    │
│        in/out: [───●●━━━━━━━]  3.2 → 6.8s                        │
│      clip [1]: @field-walking-in-market-flws ▶ [video preview]   │
│      …                                                           │
│      [+ add clip from library]                                   │
│                                                                  │
│  ▾ Product (body beats)                                          │
│      beat [0]: hook                                              │
│        asset:    @mobile-learn   ▶ [preview]                     │
│        caption:  FLW certified through Learn modules [edit]      │
│        narration: ♪ [audio preview]                              │
│         "Pay for verified service delivery — not effort." [edit] │
│      beat [1]: cycle  …                                          │
│                                                                  │
│  ▾ Music bed                                                     │
│      ♪ [audio preview: assets/shared/connect-music-bed-…mp3]     │
│      volume_db: -28                                       [edit] │
│                                                                  │
│  ▾ Voice + provider                                              │
│      provider:  elevenlabs                                       │
│      voice_id:  21m00Tcm4TlvDq8ikWAM                             │
│      model:     eleven_turbo_v2                                  │
│                                                                  │
│  ▾ Manifest (clip library)                                       │
│      @mobile-learn → drive:1dI_1Nw…  ▶ [preview]                 │
│      @mobile-pay   → drive:1vyxeW7…  ▶ [preview]                 │
│      …                                                           │
│      [+ add clip from Drive]                                     │
└──────────────────────────────────────────────────────────────────┘
```

Each section card has:

- A collapsible header with the section name + a tiny "modified" dot
  if any field below has unsaved edits.
- Inline field editors:
  - Text fields (name, tagline, caption, narration): contenteditable
    with auto-save on blur (same pattern as today).
  - Numeric fields (start_seconds, volume_db): number input with
    sensible step + min/max.
  - Asset references: a combo of (a) the alias dropdown sourced from
    the manifest, (b) an inline trim slider when the field has
    `start_seconds`/`duration_seconds`, (c) a preview video that
    seeks to the in-point on slider drag (the same scrub-while-drag
    that landed in PR #366).
  - Narration: text field + an audio preview that plays the cached
    MP3 (`assets/audio/<hash>.mp3`, served via a new
    `/assets/audio/<hash>.mp3` endpoint).
- A footer with: "Render draft" / "Rebuild HTML" / "Copy as new run"
  buttons — same actions, just colocated with the spec they affect.

## Backend changes required

The existing `/edit` op set already covers:
- `set-clip-start` — number scrub
- `set-clip-trim` — start + duration scrub
- `set-clip-asset` — alias swap
- `set-narration` — text edit

To cover the structured editor, add a generalised op:

- `set-field` — set any leaf path in the YAML. Body:
  `{ op: "set-field", path: ["product", "beats", 0, "caption"], value: "…" }`.
  ruamel.yaml round-trip preserves comments around it.

This subsumes the 4 specific ops over time; we can keep the existing
ones as conveniences and deprecate later.

Other new endpoints:

- `GET /programs/<slug>/runs/<run>/spec` — return the parsed spec as
  JSON. The editor renders from this rather than parsing YAML in the
  browser.
- `GET /assets/audio/<hash>.mp3` — serve cached voiceover audio with
  Range support. Same workspace gating as the rest.
- `GET /assets/shared/<name>` — serve shared assets (music bed). Same
  gating.

## Frontend changes required

- New component `<VideoSpecEditor />` that takes the parsed spec
  JSON + a run id and renders the sectioned card layout.
- Per-field child components: `<TextField>`, `<NumericField>`,
  `<AssetRefField>` (manifest-aware), `<NarrationField>` (text +
  audio preview), `<TrimSlider>` (extract from
  `build-clip-explorer.ts` JS into React).
- Toast-style "saved · re-rendering" banner reused from the current
  iframe pattern.

## Migration path (no big-bang)

1. Land the JSON `spec` endpoint + the structured editor as a *second
   view* on the same route — toggle button: `[ Explorer | Spec editor ]`.
2. Default to the existing iframe explorer. The editor sits beside
   it.
3. Once the editor is at parity, flip the default. Iframe stays
   available as the legacy view.
4. Phase 3 (not in this plan): drop the iframe + `build-clip-explorer.ts`
   entirely. The render no longer needs the explorer build step —
   only `programs/<slug>/runs/<run>/spec.yaml` matters.

## Open questions

- **Audio preview routing**: do we serve `assets/audio/<hash>.mp3`
  directly, or always route through `/api/w/<ws>/videos/programs/<slug>/runs/<run>/voiceover/<beat-id>`?
  The first is simpler; the second hides the cache key and lets us
  rebuild the path if the cache layout changes.
- **Edit conflict on rapid renders**: if you save field A, render
  kicks off, you save field B before render finishes — the in-flight
  render uses stale spec. Acceptable for single-writer; document
  the "wait for render to finish before next edit" loop in the UI.
- **In-container render**: the Django subprocess.Popen-into-container
  path currently can't render (esbuild platform mismatch + ffmpeg
  needs installing). Either install both in the prod image or move
  rendering to an out-of-process worker. Out of scope for this plan
  but relevant to the deploy story.
