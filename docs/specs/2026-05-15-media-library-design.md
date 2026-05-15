# Media Library — design

**Status:** draft, awaiting first implementation.
**Owner:** jjackson.
**Date:** 2026-05-15.

## Why

Today there's no curated, discoverable pool of video and audio clips that
program specs can reference. Two things are missing:

1. **Video clips** are picked ad-hoc per program — operators paste raw
   `gdrive:<file-id>` strings into the manifest, with no shared inventory of
   what footage exists across programs.
2. **Audio clips** (ElevenLabs TTS output) accumulate in
   `videos/existing_content/audio/<hash>.mp3` but the hash is one-way
   (`sha256(voice_id::model::text)[:16]`), so given a cached file you can't
   recover the voice config or the text that produced it.

The video-spec generator skill (`ace:video-from-program-page`) has no API for
"what library items are available to me?" — so the generator can't be told
to prefer reusable clips.

This design introduces a single curated **media library** at
`<workspace_root>/videos/library/`, captures audio synthesis metadata via
per-file JSON sidecars, exposes the library through MCP tools so the
generator can browse it, and adds a `library:<media>/<subfolder>/<file>`
reference syntax to `spec.yaml` so specs can point at library entries by
stable path instead of raw Drive IDs.

## Drive layout (target, post-migration)

```
<workspace_root>/videos/
├── library/
│   ├── video/
│   │   └── <subfolder>/           ← human-curated category
│   │       ├── drone-wide.mp4
│   │       ├── drone-wide.json    ← {name, description, tags}
│   │       ├── chw-walking.mp4
│   │       └── chw-walking.json
│   └── audio/                     ← machine-managed TTS output
│       ├── <hash>.mp3
│       └── <hash>.json            ← {voice_id, model, text, duration_sec, generated_at}
│
├── shared/                        ← music bed + brand assets
│   ├── connect-music-bed-pixabay.mp3
│   └── brand/connect-logo.svg
│
├── <program-slug>/                ← unchanged
│   └── runs/run-NNN/spec.yaml
└── ...
```

The pre-migration `existing_content/` folder disappears:

- `existing_content/audio/*` → `library/audio/*` (TTS cache becomes the audio
  library; sidecars added during backfill + going forward).
- `existing_content/shared/*` → `shared/*` (music bed + brand assets sit
  at the same level as `library/`, where the renderer expects them).

### Single storage pattern: per-file sidecars

Every media file has a sibling JSON sidecar with the same stem.
Folders carry no metadata files — folder name = category name.

Why per-file (not per-directory yaml):
- Audio clips are machine-generated one at a time during render. A
  per-directory yaml would have to be rewritten on every synthesis —
  race-prone if two renders run concurrently, conflict-prone if a human
  is hand-editing in parallel.
- Per-file sidecars naturally support incremental writes. The renderer
  writes `<hash>.mp3` and `<hash>.json` atomically as a pair.
- Backfill is straightforward: scan for orphan media files, write the
  missing sidecars.

### Sidecar schemas

**Video sidecar** (`<file>.json` next to `<file>.mp4`):

```json
{
  "name": "Drone — village wide",
  "description": "Slow push-in over rooftops at sunrise. 4 sec usable.",
  "tags": ["drone", "wide", "uganda", "field-footage"]
}
```

`name` and `tags` required; `description` optional.

**Audio sidecar** (`<hash>.json` next to `<hash>.mp3`):

```json
{
  "voice_id": "XB0fDUnXU5powFXDhCwa",
  "model": "eleven_turbo_v2",
  "text": "Connect helps frontline programs scale fast.",
  "duration_sec": 4.7,
  "generated_at": "2026-05-15T18:23:11Z"
}
```

All fields required; `text` is the verbatim string that was synthesized.

## Reads: Drive Changes API cache (no SQL mirror)

Library reads piggyback on the cache machinery shipped for the opps Workbench
(see `docs/learnings/opp-cache-architecture.md`):

- Per-request: one `drive.changes.list` poll (~150ms) with a Redis-stored
  `pageToken`. File IDs reported as changed invalidate matching cached
  entries; unchanged → serve from cache.
- Payload served with an ETag (`sha256` of serialized body); `If-None-Match`
  returns 304.
- Cache key includes `_KEY_VERSION` so a schema change bumps the version
  and invalidates every cached payload in one go.
- Cold load: ~Drive-list latency, writes cache.
- Warm load (95% of requests): single Changes API poll → "nothing changed"
  → 304.

SQL mirror is **not** introduced. The cache pattern is already proven to
deliver ~46-55× speedup on opps; the media library has a smaller surface
and slower churn, so we expect even higher hit rates. If cross-workspace
search/filter across thousands of items becomes a need later, swap the
storage layer behind the same API.

## Spec-level library reference syntax

`spec.yaml` manifests gain a new value form, alongside the existing
`gdrive:<id>` form:

```yaml
manifest:
  hero-shot:    "library:video/uganda-field/drone-wide.mp4"   # NEW
  chw-shot:     "library:video/uganda-field/chw-walking.mp4"  # NEW
  raw-clip:     "gdrive:1abc123..."                           # still works
```

Resolution rule: at hydrate / render time, any value beginning with
`library:` is parsed as `library:<media>/<subfolder>/<filename>` and
resolved against `<workspace_root>/videos/library/<media>/<subfolder>/<filename>`
in Drive. The resolved Drive file is then handled identically to a
`gdrive:` ref (downloaded into the same cache, fed to the same Remotion
pipeline).

Audio references are **implicit** — the existing
`narration.by_beat.<beat>: "text"` + top-level `voice.{voice_id, model}`
mechanism already produces an audio library entry on synthesis. No new
spec syntax for audio.

## Generator integration

The video-spec generator (`ace:video-from-program-page` and any future
templates) is wired to the library on two channels:

### 1. MCP-exposed list endpoints

Both new library endpoints carry `openapi_extra={"x-mcp-expose": True}`:

- `GET /api/w/{slug}/videos/library/video` → `MediaLibraryVideoOut`
- `GET /api/w/{slug}/videos/library/audio` → `MediaLibraryAudioOut`

A Claude session running the generator skill has these available as
`videos_list_library_video` / `videos_list_library_audio` MCP tools.

### 2. Prompt pre-fill

When the generator orchestrator launches the skill, it injects a compact
inventory snapshot into the prompt context — same pattern as the artifact
manifest already used in other ACE skills. The agent reads it on turn 0
and only needs to call the MCP tool if it wants to refresh after a
long-running task.

Snapshot shape (per program-spec generation):

```yaml
available_video_clips:
  - ref: "library:video/uganda-field/drone-wide.mp4"
    name: "Drone — village wide"
    tags: [drone, wide, uganda, field-footage]
    description: "Slow push-in over rooftops at sunrise."
  - ref: "library:video/uganda-field/chw-walking.mp4"
    name: "CHW walking to home visit"
    tags: [chw, walking, uganda, midshot]
  - ...
```

### 3. Generation prompt updates

Each `generate.prompt.md` (currently
`templates/60s-campaign-overview/generate.prompt.md` and
`templates/120s-program-demo/generate.prompt.md`) gets a new section
instructing the agent to:

1. Identify what each manifest slot is for (scene = field footage; product
   = app screenshot — described in the spec.template.yaml comment block).
2. Scan the library for items whose tags match the program's
   topic/country and the slot's role.
3. Prefer the library ref over raw `gdrive:` IDs.
4. Leave manifest entries empty for hand-edit if nothing fits.

### Tag conventions (documented, not enforced)

Seed two flavors:

- **Topic/identity**: `uganda`, `kenya`, `kangaroo-care`, `midwifery`, …
- **Role**: `field-footage`, `app-screenshot`, `b-roll`, `establishing`,
  `drone`, `closeup`, …

A scene-clip slot looks for `field-footage` + program-country.
A product-clip slot looks for `app-screenshot` + program-app. The
schema doesn't enforce these — they're advisory conventions that guide
the agent and humans curating the library.

## Backend (`apps/videos/library/`)

New package, three modules:

- `apps/videos/library/sidecar.py` — Pydantic models `VideoSidecar`,
  `AudioSidecar` + load/dump helpers. Parses the JSON sidecar files;
  raises a typed error if a sidecar is malformed.
- `apps/videos/library/reader.py` — `list_video_library(workspace)` and
  `list_audio_library(workspace)`. Walks Drive folders, pairs media+sidecar
  by stem, returns a typed response. Surfaces orphan media files
  (no sidecar) and orphan sidecars (no media) as `{status: "missing-*"}`
  rather than failing.
- `apps/videos/library/refs.py` — `resolve_library_ref("library:video/...")
  -> DriveFile | None`. Used by hydrate/render-time code paths.

`reader` reuses the cache infrastructure from `apps/opps/cache.py`. New
Redis-keyed cache entries `media_library:{workspace_id}:{kind}` invalidate
on any Drive Change with a `file_id` matching a library folder or file.

### Renamed / deleted modules

- `apps/videos/drive.py`:
  - Replace `EXISTING_CONTENT = "existing_content"` and the
    `EXISTING_CONTENT_{AUDIO,SHARED}` constants with two narrower
    constants: `LIBRARY = "library"`, `SHARED = "shared"`. Two helper
    pairs: `find_library_subfolder()` (under `library/{video|audio}/`)
    and `find_shared_subfolder()` (under `shared/`).
  - The pre-existing `find_existing_content()` / `read_existing_content()`
    / `list_existing_content()` family is retired. Their callers move to
    the new helpers.
- `apps/videos/service.py:684+`:
  - The sync code that pulls
    `existing_content/{audio,shared}/*` → local `assets/{audio,shared}/`
    now pulls `library/audio/*` → `assets/audio/` and
    `shared/*` → `assets/shared/`.
  - Local-disk layout `assets/audio/` + `assets/shared/` is **unchanged**
    — the Remotion renderer's expectations don't move.
- `apps/videos/management/commands/videos_migrate_existing_content.py`:
  retired. Superseded by a one-time Drive-side rename + the backfill
  command below.

### New management commands

- `videos_relocate_existing_content` — one-shot tool to perform the Drive
  rename: move `existing_content/audio/*` → `library/audio/*`, move
  `existing_content/shared/*` → `shared/*`, delete the empty
  `existing_content/` folder. Idempotent; safe to re-run.
- `videos_backfill_audio_sidecars` — walks every workspace's
  `library/audio/`, finds `<hash>.mp3` files without a sibling
  `<hash>.json`, and reconstructs the sidecar by:
  1. Walking every program's `runs/*/spec.yaml`.
  2. For each `narration.by_beat[*]` text + spec-level
     `voice.{voice_id, model}`, compute
     `cacheKey(text, voice_id, model)`.
  3. If the computed hash matches an orphan mp3, write the sidecar
     with `{voice_id, model, text, duration_sec, generated_at}` —
     `duration_sec` via ffprobe on the local cache copy if available,
     else `null`; `generated_at` from the Drive file's createdTime.
  Orphans not reconstructible from any spec stay sidecar-less and surface
  in the UI as "metadata unknown".
- `videos_backfill_video_sidecars` — for video items added by uploading
  files into `library/video/<subfolder>/` without their `.json` sidecar,
  prints a list of orphans and writes a stub sidecar
  (`{"name": "<filename without ext>", "tags": []}`) so an operator can
  fill in the rest via Drive UI.

### Renderer-side change

`video-production/connect-videos/src/lib/voiceover.ts::synthesize()`
writes the sidecar JSON immediately after the mp3:

```ts
const key = cacheKey(script, voiceId, model);
const mp3Path = path.join(cacheDir, `${key}.mp3`);
const jsonPath = path.join(cacheDir, `${key}.json`);
if (existsSync(mp3Path) && existsSync(jsonPath)) return mp3Path;
// ... ElevenLabs fetch ...
writeFileSync(mp3Path, buf);
writeFileSync(jsonPath, JSON.stringify({
  voice_id: voiceId,
  model,
  text: script,
  duration_sec: probeDuration(mp3Path),
  generated_at: new Date().toISOString(),
}, null, 2));
return mp3Path;
```

A new tiny helper `probeDuration()` shells out to ffprobe (already
available in the renderer's environment). If ffprobe fails the sidecar
omits `duration_sec` rather than crashing the render.

The local-disk cache convention `assets/audio/<hash>.{mp3,json}` mirrors
the Drive convention so the existing
`service.py::sync_existing_content_to_local()` (renamed
`sync_library_audio_to_local()`) pulls both files together.

## API

Two new endpoints in `apps/videos/api.py`:

```python
@router.get(
    "/library/video",
    response=MediaLibraryVideoOut,
    summary="List curated video library items grouped by subfolder",
    openapi_extra={"x-mcp-expose": True},
)
def list_media_library_video(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
) -> MediaLibraryVideoOut: ...

@router.get(
    "/library/audio",
    response=MediaLibraryAudioOut,
    summary="List the audio library (TTS clips with voice + text metadata)",
    openapi_extra={"x-mcp-expose": True},
)
def list_media_library_audio(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
) -> MediaLibraryAudioOut: ...
```

Response shapes (`apps/videos/schemas.py`):

```python
class VideoLibraryItemOut(BaseModel):
    ref: str                       # "library:video/<subfolder>/<filename>"
    drive_id: str
    drive_url: str                 # https://drive.google.com/file/d/<id>/view
    filename: str
    name: str
    description: str | None
    tags: list[str]
    status: Literal["ok", "missing-sidecar", "missing-media"]

class VideoLibrarySubfolderOut(BaseModel):
    subfolder: str                 # bare folder name, e.g. "uganda-field"
    items: list[VideoLibraryItemOut]

class MediaLibraryVideoOut(BaseModel):
    subfolders: list[VideoLibrarySubfolderOut]

class AudioLibraryItemOut(BaseModel):
    hash: str
    drive_id: str
    drive_url: str
    voice_id: str | None
    model: str | None
    text: str | None
    duration_sec: float | None
    generated_at: str | None       # ISO-8601
    status: Literal["ok", "missing-sidecar", "missing-media"]

class MediaLibraryAudioOut(BaseModel):
    items: list[AudioLibraryItemOut]
```

## Frontend

### New page

`frontend/src/pages/MediaLibraryPage.tsx` mounted at
`/w/:workspaceSlug/videos/library`. Two tabs (`Video` / `Audio`).
Deep-linkable via `?type=audio`.

**Video tab:** one section per subfolder. Each section header shows the
subfolder name. Below: a responsive grid of cards. Card shows item name,
tag chips, optional description, and an "Open in Drive ↗" link. No
in-page playback in v1.

**Audio tab:** flat grid (no subfolder sections). Each card shows:
- voice/model chips,
- the synthesized text (truncated to ~140 chars; full text in tooltip),
- duration,
- a generated-at relative timestamp,
- "Open in Drive ↗".

Orphan items (sidecar missing or media missing) render in a muted
"needs fixup" style with the resolver's reason. Visible by default so
they get noticed.

### Navigation

`Media library →` link added to `VideosListPage.tsx` header, top-right
of the title row. The link routes to `/w/:slug/videos/library`.

### API client

Two new functions in `frontend/src/api/videos.ts`:
- `listMediaLibraryVideo(workspaceSlug)` → `MediaLibraryVideoOut`.
- `listMediaLibraryAudio(workspaceSlug)` → `MediaLibraryAudioOut`.

Types regenerated from the OpenAPI schema via the existing
`regen-openapi.yml` workflow.

## Tests

### Backend

- `apps/videos/library/tests/test_sidecar.py` — Pydantic round-trips,
  rejects malformed JSON, accepts optional fields.
- `apps/videos/library/tests/test_reader.py` — fixture Drive layouts
  exercising: nominal video subfolder, nominal audio flat layout,
  orphan media, orphan sidecar, empty `library/` folder, missing
  `library/` folder.
- `apps/videos/library/tests/test_refs.py` — `library:` parsing,
  resolution against fake Drive, malformed refs raise a typed error.
- `apps/videos/tests/test_api_library.py` — endpoint smoke (workspace
  membership 404, cache hit/miss + 304 round-trip, MCP exposure).
- `apps/videos/tests/test_voiceover.ts` (renderer side) — sidecar
  written alongside mp3; existing-mp3 + existing-json roundtrips return
  cached path; ffprobe failure is non-fatal.
- `apps/videos/tests/test_backfill.py` — audio backfill reconstructs
  sidecars from a fixture spec corpus; orphans without a matching spec
  stay sidecar-less.

### Frontend

- `frontend/src/pages/__tests__/MediaLibraryPage.test.tsx` — renders
  video subfolders + audio rows from mocked API; orphan styling; deep
  link `?type=audio`.

## End-to-end verification (demo)

Once everything's wired:

1. Seed `library/video/` with two subfolders containing at least 2-3 mp4s
   each plus their sidecars. Categories: e.g. `uganda-field`, `kenya-clinic`.
2. Re-run `ace:video-from-program-page` against 2-3 existing Connect
   program pages (existing programs under `programs/`).
3. Verify each generated `spec.yaml` contains `library:video/…` refs in
   its manifest where appropriate; not every slot needs a library item,
   but at least scene/product slots should attempt to use one.
4. Run `npm run hydrate && npm run render` for each. Confirm renders
   succeed end-to-end.
5. Inspect `library/audio/` after renders: each render should have
   produced `<hash>.mp3` + `<hash>.json` pairs (one per beat with text).
6. Open `/w/:slug/videos/library` in the UI: video tab shows the seeded
   items grouped by subfolder; audio tab shows the freshly-synthesized
   clips with their text/voice metadata.

The verification step lives in the implementation plan, not as part of
this design.

## Out of scope (deferred)

- **Library write API / curation UI.** Operators edit
  `library/video/<subfolder>/<file>.json` in Drive directly. A
  later iteration may add a small "edit sidecar" affordance.
- **In-page video/audio playback.** Drive link only in v1. Adding
  in-page preview requires a library-media-streaming endpoint
  (analogous to the existing program `serve_media`) which can be a
  follow-up if it turns out to matter.
- **Tag-based filter UI.** Tags render as chips; filtering/search is
  a follow-up.
- **Cross-workspace library sharing.** Each workspace has its own
  Drive root and therefore its own library tree. If two workspaces
  want to share clips, copy them.
- **Audio library suggestions to the generator.** The generator
  doesn't pick from the audio library — synthesis at render time
  handles audio. A future "reuse this take" affordance would need
  spec-level syntax (not in this design).
- **Per-tag analytics** (e.g. "how often is `uganda` used?"). Easy to
  add later by counting refs across specs.

## Migration / rollout plan

The Drive relocation is the only step with downtime risk. Staged
rollout removes that risk:

1. **Phase 1 ship — dual-read code.** Land the new constants and the
   new `library/{video,audio}/` + `shared/` reader code, but have
   readers fall back to the legacy `existing_content/{audio,shared}/`
   paths when the new paths return nothing. Writers (the renderer's
   sidecar write) also write to both old and new locations during this
   phase. No Drive change yet.
2. **Phase 2 ship — relocation.** Run `videos_relocate_existing_content`
   to move the Drive folders. After this step the new code reads from
   the new locations only; the dual-read fallback is still in place
   but never triggers.
3. **Phase 3 ship — fallback removal.** Delete the dual-read fallback
   and the dual-write code. From here on, `existing_content/` does not
   exist and is not referenced.

Phases 1 and 3 are code PRs; phase 2 is a single management-command
invocation per workspace.

## Risk register

- **Drive rename incompleteness.** The relocation involves multiple
  per-folder moves (`existing_content/audio/` → parent-change to
  `library/`; `existing_content/shared/` → parent-change to workspace
  root). Each move is atomic for that folder, but the overall sequence
  isn't. The dual-read / dual-write rollout (above) makes this safe:
  renders running mid-relocation still find their files.
- **Backfill incompleteness.** The audio backfill can only reconstruct
  sidecars for hashes that match a known `(text, voice_id, model)` from
  some spec. Hashes from removed/edited specs stay metadata-less. They
  surface in the UI as "metadata unknown" — visible but not blocking.
- **Sidecar/media drift.** A human editing in Drive could remove a
  sidecar without removing the media (or vice versa). Surfaced as
  orphan cards; not silently dropped.
- **MCP tool surface change.** Adding two new MCP-exposed endpoints
  doesn't break existing consumers (the existing `videos_list_templates`
  remains). Generator skills that don't know about the library still
  function — they just won't use it.

## Open questions

None remaining. All earlier branch points were resolved in the
brainstorming session that produced this spec (see chat log
2026-05-15).

## File touchpoints (forward-looking)

Backend:
- `apps/videos/drive.py` — constants + helpers rename
- `apps/videos/service.py` — sync paths + `_audio_existing_content`
  helpers retargeted
- `apps/videos/api.py` — two new endpoints
- `apps/videos/schemas.py` — new Pydantic out-types
- `apps/videos/library/` — new package (sidecar, reader, refs, tests)
- `apps/videos/management/commands/` — relocate + backfill commands
- `apps/videos/tests/test_existing_content.py` — rename + path updates

Renderer:
- `video-production/connect-videos/src/lib/voiceover.ts` — sidecar write
- `video-production/connect-videos/src/lib/voiceover.test.ts` — new
  tests

Frontend:
- `frontend/src/api/videos.ts` — two new functions
- `frontend/src/api/generated.ts` — regenerated
- `frontend/src/pages/MediaLibraryPage.tsx` — new
- `frontend/src/pages/VideosListPage.tsx` — header link
- `frontend/src/router.tsx` (or equivalent) — new route

ACE plugin (separate PR, after this lands):
- `templates/60s-campaign-overview/generate.prompt.md` — library section
- `templates/120s-program-demo/generate.prompt.md` — library section
- `ace:video-from-program-page` skill — inventory pre-fill + MCP call
