# Replay: show what the run built

**Date**: 2026-09-26
**Status**: Approved in conversation (Jonathan, 2026-09-26), building
**Owner**: Jonathan Jackson
**Builds on**: `2026-09-17-ace-demo-player-design.md` (run replay — a
step-through mode of the Phases screen)

## Why

The first time run replay was used to explain ACE to the team, the feedback
converged on one point (Matt, Andrea): *you can't see what gets made.* The
replay shows phases and skill names turning green, but the PDD, the work order,
the Learn and Deliver apps, the Connect opportunity and the training deck are
at best a filename in an expanded row. The audience has to take it on faith
that "things are getting created and passed to the next step."

Secondary points from the same feedback that are strict improvements:

- Acronyms (PDD, OCS, LLO, FLW, HQ…) lose a watcher who doesn't know them.
- The app and opportunity links are buried in phase/skill outputs.
- An eval that never recorded a score shows an hourglass forever
  (FLW Training Guide, Phase 6) — reads as "still running" on a finished run.
- The decisions ACE made are the story, but the replay doesn't show them landing.
- 60+ beats at 1.5s is long; the presenter wants to move faster through the
  uninteresting beats.
- Ten phases is a lot for an outsider; grouping them one level up helps
  ("product setup" rather than three product phases) without hiding them.

Out of scope, deliberately: voice-over / a self-running video (that is what the
videos app renders), and the Workbench tab's chat rail (to be rebuilt on the
canopy chat widget later, and the Workbench probably retired). **Everything
here lives on the Phases screen**, built from components that don't assume it.

## What changes

### 1. The run's products, as data

`run_state.yaml` already records what each phase brought into the world under
`phases.<phase>.products.*` (the products contract,
`2026-05-11-products-block-contract.md`). The Workbench snapshot never carried
it — only the public summary read it, with its own Drive fetch.

- `RunDetail` gains `phase_products` (raw `{phase: products}`), read in
  `framework_map.map_run_detail` next to `phase_timings`. Snapshot cache
  `_KEY_VERSION` → `v11` (a stale entry would serve a run with no products
  indefinitely — the Drive files didn't change, the code did).
- `apps/opps/run_products.py` projects that into a flat **catalogue**, served
  as `current_run.products` on the snapshot and on the replay payload:

  ```
  {id, phase, key, kind, title, url, file_id, facts[{label,value}],
   producer, chatbot?{public_id, embed_key}}
  ```

  It WALKS the block rather than hard-coding one reader per product, so a
  product the plugin adds tomorrow still shows up: any mapping carrying a
  locator (`file_id`, `web_view_link`, `url`, `deep_link`, `hq_url`,
  `hq_app_id`, `par_url`, `run_url`, `public_url`, `admin_url`) is an item, and
  the walk doesn't descend into an item. `kind` is inferred from the key and
  URL (`commcare_app`, `connect_opportunity`, `connect_program`, `chatbot`,
  `deck`, `sheet`, `document`, `dashboard`, `solicitation`, `link`). The
  handful of shapes with known drift (ace#705: flat vs nested Connect blocks,
  `apps.learn` vs `learn_app`, HQ URL built from `hq_app_id` + domain) are
  handled explicitly. `nova_url` is never surfaced (no valid public URL — same
  rule as the summary). `ace_test_user` is skipped.
- `producer` is the skill that wrote the key, via the plugin's own attribution
  (`skills.resolve_product_producer`, ace#2354). `None` when unattributed.

### 2. When a product appears in the replay

The replay payload's timeline gains `products`: the catalogue plus
`reveal_seq`, the beat at which each becomes visible — its producer's
`step_end`, or, unattributed, the last `step_end` of its phase. The honesty rule
holds: nothing is shown before the beat that made it.

### 3. Viewers — in-page, for everything ACE makes

The Workbench's right rail was designed as the viewer and is a bad one for
nearly everything ACE produces now (decks, apps, dashboards). New
`frontend/src/components/viewers/`:

- **`DriveFileViewer`** — fetches the new view endpoint and renders by the
  response's content type: markdown (Docs), CSV table (Sheets), PDF (Slides,
  exported server-side, so the viewer needs no Google sign-in), image, video,
  plain text / YAML. Module-level cache so a warmed file opens instantly.
- **`ProductViewer`** — dispatches on `kind`: a Drive-backed product renders
  its file; a CommCare app renders a card (name, build status, HQ link) plus
  the producing skill's structure summary; a Connect opportunity/program, a
  dashboard, a solicitation render a fact card with the live link; the OCS
  chatbot renders its facts and can mount the real widget to talk to it.
- **`ViewerDialog`** (click to open, any time) and **`Spotlight`** (the replay
  pop-up) share that body. A `ViewerProvider` context exposes `open(...)` so
  any surface — the products strip, a skill's artifact list, the flow panel —
  opens the same viewer, and a later widget-hosted page can too.

**View endpoint** — `GET /api/w/{ws}/opps/{slug}/artifacts/{file_id}/view?run_id=`.
The id must belong to the run — a step artifact, a file in the run folder, or a
product's `file_id` — resolved against the cached rich snapshot; that scan is
the authorization boundary, same as `download`. Representation by the file's
real Drive MIME: prose Doc → markdown export (passed through verbatim; the
renderer is CommonMark), YAML/JSON Doc → plain text, Slides → PDF export,
Sheet → CSV, image/video/PDF → bytes (capped at 50 MB → 413), text → text,
anything else → 415 (the viewer offers Drive). `X-Artifact-Name` and
`X-Drive-Link` headers; `Cache-Control: private, max-age=300`.
`DriveClient.export_bytes` is added for the binary exports (the existing
`get_content` decodes to text, which a PDF can't survive).

### 4. The Phases screen

- **Products strip** under the replay bar (and without replay, as "What this
  run built"): one chip per product, greyed until revealed, click to view.
  Answers "don't bury the app and opp links".
- **Spotlight**: when the cursor lands on a beat that reveals products, they
  pop up over the screen ("Just built · Phase 3 · by Build Learn app"). While
  playing, each holds ~4.5s (playback waits), then closes and play resumes.
  Stepping by hand, it stays until → (next product, then next beat), ← or Esc.
  Pop-ups can be switched off (P).
- **Flow panel** (right rail, replay only): for the current skill, what it
  **took in** (from which earlier phase/skill) and what it **handed on** (to
  which later skills), from the plugin's artifact manifest (`producedBy` /
  `consumedBy` — 129 of 159 entries declare consumers). Served as
  `timeline.flow` so the frontend doesn't parse the plugin. Inputs link to the
  run's real file where one exists and has been reached.
- **Decisions as they land**: in replay the Decisions panel shows only
  decisions whose skill has finished (a decision with no skill lands when its
  phase's last step does), and editing is off. Each skill's drawer gains a
  Decisions section — what it decided, and whether a human overrode it.
- **Highlights mode** (H): Next / Prev / Play move only between phase starts
  and beats that reveal a product, fail, or record decisions.
- **Phase groups** over the step track: Design (1–2) · Product setup (3–5) ·
  Training & demo (6–7) · Partner & launch (8–10). Phase names are the
  plugin's; a phase the map doesn't know stays ungrouped rather than guessed.
- **Glossary**: known acronyms and product names (PDD, OCS, LLO, FLW, HQ, QA,
  UAT, RAG, KPI, Nova, Learn app, Deliver app) get a dotted underline and a
  plain-English definition on hover wherever phase, skill and product names
  render.
- **No eternal hourglass**: an eval with no score on a step that has finished
  reads "no score" ("the eval never recorded a score"); ⏳ only while the step
  is actually running or pending. Same for QA's incomplete verdict.

## Testing

- `run_products`: the walker against the fixture shapes the summary tests
  already pin (nested + flat Connect, `apps.learn` vs `learn_app`, training
  docs, synthetic dashboards, chatbot), dedupe, `nova_url` suppression,
  producer attribution.
- Replay: `reveal_seq` (attributed, unattributed, phase never ran), `flow`
  built from a stub manifest.
- View endpoint: authorization (unknown id → 404), representation per MIME,
  size cap, product file ids accepted.
- `_KEY_VERSION` ledger test updated to v11.
- Frontend (vitest): glossary splitting, highlight-beat computation, product
  reveal, decision reveal, eval/QA chip on a finished step, viewer dispatch by
  content type.
