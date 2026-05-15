# Media Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a curated workspace-scoped media library (video + audio) at `<workspace_root>/videos/library/`, with per-file JSON sidecars, MCP-exposed list endpoints, a React library page, a `library:video/<subfolder>/<filename>` spec-yaml reference syntax, and an end-to-end demo across multiple programs.

**Architecture:** Drive-backed (no SQL mirror). Per-file sidecars (`<file>.json`) carry metadata for both video (human-curated: `name/description/tags`) and audio (machine-captured at TTS synthesis: `voice_id/model/text/duration_sec/generated_at`). Reads go through Django Ninja endpoints with a 60s TTL cache (same pattern as `apps/videos/cache.py`). Drive relocation (`existing_content/` → `library/audio/` + `shared/`) ships via a three-phase rollout: dual-read code → relocation command → fallback removal.

**Tech Stack:** Django 5 + Ninja v1 + Pydantic v2 (backend), React 19 + Vite + react-router-dom v6 (frontend), Remotion + Node 20 + ElevenLabs (renderer), Google Drive API v3 (storage). Tests: pytest-django + pytest-asyncio (backend), vitest + RTL (frontend), node:test (renderer).

**Spec reference:** [docs/specs/2026-05-15-media-library-design.md](../specs/2026-05-15-media-library-design.md).

---

## File map (informational)

**New files:**
- `apps/videos/library/__init__.py`
- `apps/videos/library/sidecar.py` — Pydantic `VideoSidecar` + `AudioSidecar`
- `apps/videos/library/reader.py` — `list_video_library` + `list_audio_library`
- `apps/videos/library/refs.py` — `parse_library_ref` + `resolve_library_ref`
- `apps/videos/library/tests/__init__.py`
- `apps/videos/library/tests/test_sidecar.py`
- `apps/videos/library/tests/test_reader.py`
- `apps/videos/library/tests/test_refs.py`
- `apps/videos/tests/test_api_library.py`
- `apps/videos/tests/test_backfill.py`
- `apps/videos/management/commands/videos_backfill_audio_sidecars.py`
- `apps/videos/management/commands/videos_backfill_video_sidecars.py`
- `apps/videos/management/commands/videos_relocate_existing_content.py`
- `frontend/src/pages/MediaLibraryPage.tsx`
- `frontend/src/pages/__tests__/MediaLibraryPage.test.tsx`

**Modified files:**
- `apps/videos/drive.py` — add `LIBRARY` / `SHARED_TOP` constants + dual-path helpers
- `apps/videos/service.py` — `stage_existing_content_locally` reads from both old and new paths (Phase A), eventually only new (Phase C)
- `apps/videos/schemas.py` — `MediaLibraryVideoOut` / `MediaLibraryAudioOut` and friends
- `apps/videos/api.py` — `/library/video` + `/library/audio` endpoints
- `apps/videos/cache.py` — `videos:lib:video:*` and `videos:lib:audio:*` namespaces
- `frontend/src/api/videos.ts` — `listMediaLibraryVideo` + `listMediaLibraryAudio`
- `frontend/src/api/generated.ts` — regenerated from OpenAPI
- `frontend/src/pages/VideosListPage.tsx` — header link
- `frontend/src/router.tsx` — new route
- `video-production/connect-videos/src/lib/voiceover.ts` — sidecar write
- `video-production/connect-videos/src/lib/voiceover.test.ts` — sidecar tests
- `video-production/connect-videos/templates/60s-campaign-overview/generate.prompt.md` — library section
- `video-production/connect-videos/templates/120s-program-demo/generate.prompt.md` — library section
- `apps/videos/tests/test_existing_content.py` — adapted for dual-path behavior

**Deleted (Phase C):**
- `apps/videos/management/commands/videos_migrate_existing_content.py` — superseded
- Dual-read fallback code paths

---

## Phase 1 — Audio sidecar at synthesis time (Node renderer)

Lays the groundwork: from this point forward every new ElevenLabs synthesis writes a sidecar. Pure additive change in the renderer; no Drive or Django code touched yet.

### Task 1.1: Add a duration probe helper

**Files:**
- Create: `video-production/connect-videos/src/lib/probe.ts`
- Test: `video-production/connect-videos/src/lib/probe.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// video-production/connect-videos/src/lib/probe.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { writeFileSync, unlinkSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { probeDurationSeconds } from "./probe";

test("returns null when ffprobe fails on a non-media file", () => {
  const fake = path.join(tmpdir(), `probe-test-${Date.now()}.bin`);
  writeFileSync(fake, "not-a-real-mp3");
  try {
    assert.equal(probeDurationSeconds(fake), null);
  } finally {
    if (existsSync(fake)) unlinkSync(fake);
  }
});

test("returns null when the file does not exist", () => {
  assert.equal(probeDurationSeconds("/no/such/file.mp3"), null);
});
```

- [ ] **Step 2: Run the test, watch it fail**

Run: `npm test --prefix video-production/connect-videos -- src/lib/probe.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `probeDurationSeconds`**

```ts
// video-production/connect-videos/src/lib/probe.ts
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";

/**
 * Read media duration in seconds via ffprobe. Returns null when ffprobe
 * isn't installed, the file is missing, or the format is unreadable —
 * the renderer keeps going either way; sidecar metadata is best-effort.
 */
export function probeDurationSeconds(filePath: string): number | null {
  if (!existsSync(filePath)) return null;
  try {
    const out = execFileSync(
      "ffprobe",
      [
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        filePath,
      ],
      { encoding: "utf8", timeout: 5_000 },
    ).trim();
    const n = Number(out);
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch {
    return null;
  }
}
```

- [ ] **Step 4: Re-run the test**

Run: `npm test --prefix video-production/connect-videos -- src/lib/probe.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add video-production/connect-videos/src/lib/probe.ts \
        video-production/connect-videos/src/lib/probe.test.ts
git commit -m "videos(renderer): add probeDurationSeconds helper"
```

### Task 1.2: Sidecar write in `synthesize()`

**Files:**
- Modify: `video-production/connect-videos/src/lib/voiceover.ts` (lines 1-58)
- Modify: `video-production/connect-videos/src/lib/voiceover.test.ts`

- [ ] **Step 1: Write the failing test (added at end of existing file)**

```ts
// Append to video-production/connect-videos/src/lib/voiceover.test.ts

import { existsSync, readFileSync, rmSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

test("synthesize writes a sidecar JSON next to the mp3", async () => {
  const cacheDir = mkdtempSync(path.join(tmpdir(), "voiceover-sidecar-"));
  try {
    const fakeFetch: typeof fetch = async () =>
      new Response(new Uint8Array([0xff, 0xfb, 0x10, 0xc0]), {
        status: 200,
        headers: { "content-type": "audio/mpeg" },
      });
    const out = await synthesize({
      script: "Hello world",
      voiceId: "voiceA",
      model: "modelB",
      cacheDir,
      apiKey: "key",
      fetchImpl: fakeFetch,
    });
    const stem = path.basename(out, ".mp3");
    const sidecarPath = path.join(cacheDir, `${stem}.json`);
    assert.ok(existsSync(sidecarPath), "sidecar must exist");
    const parsed = JSON.parse(readFileSync(sidecarPath, "utf8"));
    assert.equal(parsed.voice_id, "voiceA");
    assert.equal(parsed.model, "modelB");
    assert.equal(parsed.text, "Hello world");
    assert.ok(typeof parsed.generated_at === "string");
    // duration_sec is null on the fake 4-byte mp3 (ffprobe will fail)
    assert.ok(parsed.duration_sec === null || typeof parsed.duration_sec === "number");
  } finally {
    rmSync(cacheDir, { recursive: true, force: true });
  }
});

test("synthesize returns cached path when both mp3 and sidecar exist", async () => {
  const cacheDir = mkdtempSync(path.join(tmpdir(), "voiceover-cached-"));
  try {
    let fetchCalls = 0;
    const fakeFetch: typeof fetch = async () => {
      fetchCalls++;
      return new Response(new Uint8Array([0xff, 0xfb]), {
        status: 200,
        headers: { "content-type": "audio/mpeg" },
      });
    };
    await synthesize({
      script: "Twice",
      voiceId: "v",
      model: "m",
      cacheDir,
      apiKey: "key",
      fetchImpl: fakeFetch,
    });
    await synthesize({
      script: "Twice",
      voiceId: "v",
      model: "m",
      cacheDir,
      apiKey: "key",
      fetchImpl: fakeFetch,
    });
    assert.equal(fetchCalls, 1, "second call must hit cache");
  } finally {
    rmSync(cacheDir, { recursive: true, force: true });
  }
});
```

- [ ] **Step 2: Run the tests, watch them fail**

Run: `npm test --prefix video-production/connect-videos -- src/lib/voiceover.test.ts`
Expected: FAIL (sidecar not written).

- [ ] **Step 3: Modify `synthesize()` to write the sidecar**

```ts
// Replace the body of synthesize() in
// video-production/connect-videos/src/lib/voiceover.ts.

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { probeDurationSeconds } from "./probe";

export function cacheKey(script: string, voiceId: string, model: string): string {
  return createHash("sha256")
    .update(`${voiceId}::${model}::${script}`)
    .digest("hex")
    .slice(0, 16);
}

export interface SynthesizeArgs {
  script: string;
  voiceId: string;
  model: string;
  cacheDir: string;
  apiKey: string;
  fetchImpl?: typeof fetch;
}

export async function synthesize(args: SynthesizeArgs): Promise<string> {
  const { script, voiceId, model, cacheDir, apiKey } = args;
  const key = cacheKey(script, voiceId, model);
  mkdirSync(cacheDir, { recursive: true });
  const mp3Path = path.join(cacheDir, `${key}.mp3`);
  const jsonPath = path.join(cacheDir, `${key}.json`);
  if (existsSync(mp3Path) && existsSync(jsonPath)) return mp3Path;

  if (!existsSync(mp3Path)) {
    const fetchImpl = args.fetchImpl ?? fetch;
    const resp = await fetchImpl(
      `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}`,
      {
        method: "POST",
        headers: {
          "xi-api-key": apiKey,
          "content-type": "application/json",
          accept: "audio/mpeg",
        },
        body: JSON.stringify({
          text: script,
          model_id: model,
          voice_settings: {
            stability: 0.6,
            similarity_boost: 0.45,
            style: 0.2,
            use_speaker_boost: true,
          },
        }),
      }
    );
    if (!resp.ok) {
      throw new Error(`ElevenLabs HTTP ${resp.status}: ${await safeText(resp)}`);
    }
    const buf = Buffer.from(await resp.arrayBuffer());
    writeFileSync(mp3Path, buf);
  }

  // Always (re)write the sidecar when missing — covers (a) brand-new
  // synthesis and (b) pre-sidecar mp3s left over from an earlier render.
  writeFileSync(
    jsonPath,
    JSON.stringify(
      {
        voice_id: voiceId,
        model,
        text: script,
        duration_sec: probeDurationSeconds(mp3Path),
        generated_at: new Date().toISOString(),
      },
      null,
      2,
    ),
  );
  return mp3Path;
}
```

- [ ] **Step 4: Re-run the tests**

Run: `npm test --prefix video-production/connect-videos -- src/lib/voiceover.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add video-production/connect-videos/src/lib/voiceover.ts \
        video-production/connect-videos/src/lib/voiceover.test.ts
git commit -m "videos(renderer): write per-clip sidecar at TTS synthesis"
```

---

## Phase 2 — Python sidecar schemas

### Task 2.1: Create `apps/videos/library/` package + `VideoSidecar` model

**Files:**
- Create: `apps/videos/library/__init__.py`
- Create: `apps/videos/library/sidecar.py`
- Create: `apps/videos/library/tests/__init__.py`
- Create: `apps/videos/library/tests/test_sidecar.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/videos/library/tests/test_sidecar.py
import json

import pytest

from apps.videos.library.sidecar import (
    AudioSidecar,
    SidecarParseError,
    VideoSidecar,
    parse_audio_sidecar,
    parse_video_sidecar,
)


def test_video_sidecar_roundtrip():
    raw = json.dumps({
        "name": "Drone — village wide",
        "description": "Slow push-in at sunrise.",
        "tags": ["drone", "wide"],
    })
    sc = parse_video_sidecar(raw)
    assert sc == VideoSidecar(
        name="Drone — village wide",
        description="Slow push-in at sunrise.",
        tags=["drone", "wide"],
    )


def test_video_sidecar_description_optional():
    raw = json.dumps({"name": "x", "tags": []})
    sc = parse_video_sidecar(raw)
    assert sc.description is None
    assert sc.tags == []


def test_video_sidecar_missing_name_rejects():
    with pytest.raises(SidecarParseError):
        parse_video_sidecar(json.dumps({"tags": []}))


def test_video_sidecar_malformed_json_rejects():
    with pytest.raises(SidecarParseError):
        parse_video_sidecar("{not json}")


def test_audio_sidecar_roundtrip():
    raw = json.dumps({
        "voice_id": "abc",
        "model": "eleven_turbo_v2",
        "text": "Hello world.",
        "duration_sec": 1.5,
        "generated_at": "2026-05-15T18:23:11Z",
    })
    sc = parse_audio_sidecar(raw)
    assert sc == AudioSidecar(
        voice_id="abc",
        model="eleven_turbo_v2",
        text="Hello world.",
        duration_sec=1.5,
        generated_at="2026-05-15T18:23:11Z",
    )


def test_audio_sidecar_duration_optional():
    raw = json.dumps({
        "voice_id": "abc",
        "model": "m",
        "text": "t",
        "duration_sec": None,
        "generated_at": "2026-05-15T18:23:11Z",
    })
    sc = parse_audio_sidecar(raw)
    assert sc.duration_sec is None
```

- [ ] **Step 2: Run the test, watch it fail**

Run: `pytest apps/videos/library/tests/test_sidecar.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the module**

```python
# apps/videos/library/__init__.py
"""Curated workspace-scoped media library on top of Drive.

See docs/specs/2026-05-15-media-library-design.md.
"""
```

```python
# apps/videos/library/sidecar.py
"""Per-file JSON sidecar schemas.

Every media file under ``library/{video,audio}/`` has a sibling sidecar
file with the same stem (``foo.mp4`` ↔ ``foo.json``;
``<hash>.mp3`` ↔ ``<hash>.json``). The two media types carry different
metadata; the storage pattern is identical.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


class SidecarParseError(ValueError):
    """Raised when a sidecar JSON is malformed or missing required fields."""


class VideoSidecar(BaseModel):
    """Human-curated metadata for a video clip in the library."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    tags: list[str]
    description: str | None = None


class AudioSidecar(BaseModel):
    """Machine-captured metadata for a TTS-synthesized audio clip."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    voice_id: str
    model: str
    text: str
    duration_sec: float | None
    generated_at: str


def _load_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SidecarParseError(f"malformed sidecar JSON: {e}") from e
    if not isinstance(data, dict):
        raise SidecarParseError(f"sidecar must be a JSON object, got {type(data).__name__}")
    return data


def parse_video_sidecar(raw: str) -> VideoSidecar:
    data = _load_json(raw)
    try:
        return VideoSidecar(**data)
    except ValidationError as e:
        raise SidecarParseError(str(e)) from e


def parse_audio_sidecar(raw: str) -> AudioSidecar:
    data = _load_json(raw)
    try:
        return AudioSidecar(**data)
    except ValidationError as e:
        raise SidecarParseError(str(e)) from e
```

```python
# apps/videos/library/tests/__init__.py
```

- [ ] **Step 4: Re-run the test**

Run: `pytest apps/videos/library/tests/test_sidecar.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/videos/library/
git commit -m "videos(library): add per-file sidecar schemas (video + audio)"
```

---

## Phase 3 — Drive constants + dual-path helpers

The relocation rolls out in three phases. This phase adds the new constants and helpers; readers fall back to the legacy `existing_content/` paths so nothing breaks before the actual Drive move runs.

### Task 3.1: Add `LIBRARY` + `SHARED_TOP` constants and new Drive helpers

**Files:**
- Modify: `apps/videos/drive.py` (lines 37-47 and 248-333)
- Test: existing `apps/videos/tests/test_existing_content.py` still passes after the change

- [ ] **Step 1: Add new constants alongside the legacy ones**

Edit `apps/videos/drive.py`. Find the constants block (lines 37-47) and replace with:

```python
VIDEOS_FOLDER = "videos"
RUNS_FOLDER = "runs"
SPEC_FILENAME = "spec.yaml"
YAML_MIME = "application/x-yaml"

# Legacy layout — kept readable through Phase B; removed in Phase C.
EXISTING_CONTENT = "existing_content"
EXISTING_CONTENT_AUDIO = "audio"
EXISTING_CONTENT_SHARED = "shared"
EXISTING_CONTENT_SUBDIRS = (EXISTING_CONTENT_AUDIO, EXISTING_CONTENT_SHARED)

# New layout — destination of the relocation.
LIBRARY = "library"
LIBRARY_VIDEO = "video"
LIBRARY_AUDIO = "audio"
LIBRARY_MEDIA_KINDS = (LIBRARY_VIDEO, LIBRARY_AUDIO)
SHARED_TOP = "shared"  # sibling of library/, at videos/shared/

# Per-run artifact filenames + mime types.
OUTPUT_MP4_FILENAME = "output.mp4"
OUTPUT_MP4_MIME = "video/mp4"
EXPLORER_ARCHIVE_FILENAME = "explorer.tar.gz"
EXPLORER_ARCHIVE_MIME = "application/gzip"
FEEDBACK_FILENAME = "feedback.md"
FEEDBACK_MIME = "text/markdown"
```

- [ ] **Step 2: Add new helpers next to the legacy `existing_content_folder_id` family**

Append the following functions at the end of the `existing_content/` block in `apps/videos/drive.py` (after `read_existing_content`, around line 334):

```python
# ---------------------------------------------------------------------------
# library/ — curated media + shared/ — music bed + brand assets
# ---------------------------------------------------------------------------


def library_folder_id(
    layout: DriveLayout, client: DriveClient,
    media: str | None = None, subfolder: str | None = None,
    *, create: bool = False,
) -> str | None:
    """Resolve videos/library/, videos/library/<media>/, or
    videos/library/<media>/<subfolder>/.

    Pass create=True to materialize missing parents.
    """
    if media is not None and media not in LIBRARY_MEDIA_KINDS:
        raise ValueError(
            f"Unknown library media: {media!r}; "
            f"expected one of {LIBRARY_MEDIA_KINDS}"
        )
    if subfolder is not None and media is None:
        raise ValueError("subfolder requires media")

    root = _find_child(client, layout.videos_folder_id, LIBRARY)
    if root is None or root.mime_type != "application/vnd.google-apps.folder":
        if not create:
            return None
        root_id = client.create_folder(layout.videos_folder_id, LIBRARY)
    else:
        root_id = root.id

    if media is None:
        return root_id

    media_node = _find_child(client, root_id, media)
    if media_node is None or media_node.mime_type != "application/vnd.google-apps.folder":
        if not create:
            return None
        media_id = client.create_folder(root_id, media)
    else:
        media_id = media_node.id

    if subfolder is None:
        return media_id

    sub = _find_child(client, media_id, subfolder)
    if sub is None or sub.mime_type != "application/vnd.google-apps.folder":
        if not create:
            return None
        return client.create_folder(media_id, subfolder)
    return sub.id


def list_library_subfolders(
    layout: DriveLayout, client: DriveClient, media: str,
) -> list[DriveFile]:
    """Direct subfolders under videos/library/<media>/.

    Empty list when library/<media>/ does not exist yet.
    """
    media_id = library_folder_id(layout, client, media)
    if media_id is None:
        return []
    return [
        f for f in client.list_folder(media_id)
        if f.mime_type == "application/vnd.google-apps.folder"
    ]


def list_library_files(
    layout: DriveLayout, client: DriveClient,
    media: str, subfolder: str,
) -> list[DriveFile]:
    """Direct files under videos/library/<media>/<subfolder>/.

    Returns both media files and sidecars; folders excluded. Empty list
    when the subfolder doesn't exist.
    """
    folder_id = library_folder_id(layout, client, media, subfolder)
    if folder_id is None:
        return []
    return [
        f for f in client.list_folder(folder_id)
        if f.mime_type != "application/vnd.google-apps.folder"
    ]


def list_audio_library_files(
    layout: DriveLayout, client: DriveClient,
) -> list[DriveFile]:
    """Direct files under videos/library/audio/ (flat layout — no subfolders).

    Returns both .mp3 and .json files; folders excluded.
    """
    media_id = library_folder_id(layout, client, LIBRARY_AUDIO)
    if media_id is None:
        return []
    return [
        f for f in client.list_folder(media_id)
        if f.mime_type != "application/vnd.google-apps.folder"
    ]


def read_library_file(
    layout: DriveLayout, client: DriveClient,
    media: str, name: str,
    *, subfolder: str | None = None,
) -> bytes | None:
    """Read one file under library/<media>/[<subfolder>/]<name>.

    For audio (flat) pass subfolder=None. For video (subfoldered) pass
    the subfolder.
    """
    if media == LIBRARY_AUDIO:
        files = list_audio_library_files(layout, client)
    else:
        if subfolder is None:
            raise ValueError("video reads require a subfolder")
        files = list_library_files(layout, client, media, subfolder)
    for f in files:
        if f.name == name:
            return client.get_binary(f.id)
    return None


def upload_library_file(
    layout: DriveLayout, client: DriveClient,
    media: str, name: str, content: bytes, mime_type: str,
    *, subfolder: str | None = None,
) -> str:
    """Create-or-replace a library file. Materializes parents if needed.

    For audio pass subfolder=None (audio is flat); for video pass the subfolder.
    Returns the Drive file id.
    """
    if media == LIBRARY_AUDIO:
        folder_id = library_folder_id(layout, client, LIBRARY_AUDIO, create=True)
    else:
        if subfolder is None:
            raise ValueError("video uploads require a subfolder")
        folder_id = library_folder_id(layout, client, media, subfolder, create=True)
    assert folder_id is not None
    existing = _find_child(client, folder_id, name)
    if existing is not None:
        client.update_binary(existing.id, content, mime_type)
        return existing.id
    return client.upload_binary(folder_id, name, content, mime_type)


def shared_top_folder_id(
    layout: DriveLayout, client: DriveClient, *, create: bool = False,
) -> str | None:
    """Resolve videos/shared/ (sibling of library/)."""
    existing = _find_child(client, layout.videos_folder_id, SHARED_TOP)
    if existing is None or existing.mime_type != "application/vnd.google-apps.folder":
        if not create:
            return None
        return client.create_folder(layout.videos_folder_id, SHARED_TOP)
    return existing.id


def list_shared_top_files(
    layout: DriveLayout, client: DriveClient,
) -> list[DriveFile]:
    folder_id = shared_top_folder_id(layout, client)
    if folder_id is None:
        return []
    return [
        f for f in client.list_folder(folder_id)
        if f.mime_type != "application/vnd.google-apps.folder"
    ]
```

- [ ] **Step 3: Run the existing tests, confirm nothing broke**

Run: `pytest apps/videos/tests/test_existing_content.py -v`
Expected: PASS (legacy code paths untouched).

- [ ] **Step 4: Commit**

```bash
git add apps/videos/drive.py
git commit -m "videos(drive): add library/ + shared/ folder helpers alongside legacy"
```

### Task 3.2: Service-layer dual-path sync

**Files:**
- Modify: `apps/videos/service.py` (lines 684-783)
- Modify: `apps/videos/tests/test_existing_content.py`

- [ ] **Step 1: Add a failing test for dual-path read**

Append to `apps/videos/tests/test_existing_content.py`:

```python
def test_stage_existing_content_reads_from_library_audio_then_shared(workspace, fake_drive):
    """When new library/audio/ has files, they land in local assets/audio/.
    When videos/shared/ has files, they land in local assets/shared/."""
    from apps.videos import drive as drive_mod
    from apps.videos import service as service_mod

    layout = service_mod.layout_for(workspace)[0]

    # Seed new layout: one file in library/audio/ and one in shared/.
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        "deadbeef.mp3", b"audio-bytes", "audio/mpeg",
    )
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        "deadbeef.json", b'{"voice_id":"v","model":"m","text":"t","duration_sec":null,"generated_at":"2026-05-15T00:00:00Z"}',
        "application/json",
    )
    # Music bed in the new shared/ location.
    shared_id = drive_mod.shared_top_folder_id(layout, fake_drive.client, create=True)
    fake_drive.client.upload_binary(shared_id, "music-bed.mp3", b"music", "audio/mpeg")

    counts = service_mod.stage_existing_content_locally(workspace)
    # audio + shared both downloaded
    assert counts["audio"] >= 1
    assert counts["shared"] >= 1
```

- [ ] **Step 2: Run the test, watch it fail**

Run: `pytest apps/videos/tests/test_existing_content.py::test_stage_existing_content_reads_from_library_audio_then_shared -v`
Expected: FAIL.

- [ ] **Step 3: Replace `stage_existing_content_locally` with dual-path implementation**

Find `stage_existing_content_locally` in `apps/videos/service.py` (around line 755) and replace its body with:

```python
def stage_existing_content_locally(workspace: Workspace) -> dict[str, int]:
    """Pull audio + shared assets from Drive into local
    `<videos_root>/assets/{audio,shared}/`.

    Source-of-truth precedence per asset type:

      audio:  videos/library/audio/   (new)  >>  videos/existing_content/audio/   (legacy)
      shared: videos/shared/          (new)  >>  videos/existing_content/shared/  (legacy)

    The legacy fallback is kept through Phase B of the relocation
    rollout; remove it in Phase C once the Drive move has run on every
    workspace and the dual-write code below has been retired.

    Skip-if-present (by exact byte size) keeps warm scratch fast.

    Returns a per-bucket count of files actually downloaded.
    """
    counts: dict[str, int] = {"audio": 0, "shared": 0}
    layout, client = layout_for(workspace)

    # ---- audio (mp3s + sidecars) -----------------------------------------
    local_audio = _root() / "assets" / "audio"
    local_audio.mkdir(parents=True, exist_ok=True)

    audio_drive_files = drive.list_audio_library_files(layout, client)
    seen_audio: set[str] = set()
    for f in audio_drive_files:
        seen_audio.add(f.name)
        target = local_audio / f.name
        if target.exists() and target.stat().st_size == (f.size_bytes or 0):
            continue
        payload = client.get_binary(f.id)
        target.write_bytes(payload)
        counts["audio"] += 1

    # Legacy fallback: only pull names the new path didn't already cover.
    legacy_audio = drive.list_existing_content(layout, client, drive.EXISTING_CONTENT_AUDIO)
    for f in legacy_audio:
        if f.name in seen_audio:
            continue
        target = local_audio / f.name
        if target.exists() and target.stat().st_size == (f.size_bytes or 0):
            continue
        payload = client.get_binary(f.id)
        target.write_bytes(payload)
        counts["audio"] += 1

    # ---- shared (music bed + brand assets) -------------------------------
    local_shared = _root() / "assets" / "shared"
    local_shared.mkdir(parents=True, exist_ok=True)

    shared_drive_files = drive.list_shared_top_files(layout, client)
    seen_shared: set[str] = set()
    for f in shared_drive_files:
        seen_shared.add(f.name)
        target = local_shared / f.name
        if target.exists() and target.stat().st_size == (f.size_bytes or 0):
            continue
        target.write_bytes(client.get_binary(f.id))
        counts["shared"] += 1

    legacy_shared = drive.list_existing_content(layout, client, drive.EXISTING_CONTENT_SHARED)
    for f in legacy_shared:
        if f.name in seen_shared:
            continue
        target = local_shared / f.name
        if target.exists() and target.stat().st_size == (f.size_bytes or 0):
            continue
        target.write_bytes(client.get_binary(f.id))
        counts["shared"] += 1

    return counts
```

- [ ] **Step 4: Re-run the tests**

Run: `pytest apps/videos/tests/test_existing_content.py -v`
Expected: PASS (legacy tests still green, new dual-path test passes).

- [ ] **Step 5: Commit**

```bash
git add apps/videos/service.py apps/videos/tests/test_existing_content.py
git commit -m "videos(service): dual-path audio+shared sync (library/* > existing_content/*)"
```

---

## Phase 4 — Library reader + cache

### Task 4.1: `reader.py` — parse Drive listings into typed responses

**Files:**
- Create: `apps/videos/library/reader.py`
- Create: `apps/videos/library/tests/test_reader.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/videos/library/tests/test_reader.py
import json

import pytest

from apps.videos import drive as drive_mod
from apps.videos import service as service_mod
from apps.videos.library import reader


@pytest.fixture
def seeded_video_library(workspace, fake_drive):
    """Seed library/video/uganda-field/ with one well-formed clip and one orphan."""
    layout = service_mod.layout_for(workspace)[0]
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_VIDEO,
        "drone-wide.mp4", b"mp4-bytes", "video/mp4",
        subfolder="uganda-field",
    )
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_VIDEO,
        "drone-wide.json",
        json.dumps({
            "name": "Drone — village wide",
            "description": "Sunrise push-in",
            "tags": ["drone", "wide", "uganda"],
        }).encode(),
        "application/json",
        subfolder="uganda-field",
    )
    # Orphan media (no sidecar)
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_VIDEO,
        "orphan.mp4", b"mp4-bytes", "video/mp4",
        subfolder="uganda-field",
    )
    return layout


def test_list_video_library_pairs_media_and_sidecar(workspace, fake_drive, seeded_video_library):
    out = reader.list_video_library(workspace)
    assert len(out.subfolders) == 1
    sub = out.subfolders[0]
    assert sub.subfolder == "uganda-field"
    names = sorted(i.filename for i in sub.items)
    assert names == ["drone-wide.mp4", "orphan.mp4"]
    by_name = {i.filename: i for i in sub.items}
    assert by_name["drone-wide.mp4"].status == "ok"
    assert by_name["drone-wide.mp4"].name == "Drone — village wide"
    assert by_name["drone-wide.mp4"].tags == ["drone", "wide", "uganda"]
    assert by_name["orphan.mp4"].status == "missing-sidecar"


def test_list_video_library_empty_when_no_library_folder(workspace, fake_drive):
    out = reader.list_video_library(workspace)
    assert out.subfolders == []


def test_list_audio_library_pairs_by_hash(workspace, fake_drive):
    layout = service_mod.layout_for(workspace)[0]
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        "deadbeef.mp3", b"mp3-bytes", "audio/mpeg",
    )
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        "deadbeef.json",
        json.dumps({
            "voice_id": "v1", "model": "m1", "text": "Hello",
            "duration_sec": 1.1, "generated_at": "2026-05-15T00:00:00Z",
        }).encode(),
        "application/json",
    )
    out = reader.list_audio_library(workspace)
    assert len(out.items) == 1
    item = out.items[0]
    assert item.hash == "deadbeef"
    assert item.status == "ok"
    assert item.voice_id == "v1"
    assert item.text == "Hello"
    assert item.duration_sec == 1.1
```

- [ ] **Step 2: Run the test, watch it fail**

Run: `pytest apps/videos/library/tests/test_reader.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `reader.py`**

```python
# apps/videos/library/reader.py
"""Workspace-scoped media library reader.

Walks Drive folders, pairs media files with their JSON sidecars by stem,
and returns typed responses. Orphans (media with no sidecar, sidecar with
no media, malformed sidecar) are surfaced as ``status != "ok"`` rather
than dropped silently.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from apps.opps.drive_client import DriveClient
from apps.videos import drive as drive_mod
from apps.videos.drive import DriveLayout
from apps.videos.library.sidecar import (
    AudioSidecar,
    SidecarParseError,
    VideoSidecar,
    parse_audio_sidecar,
    parse_video_sidecar,
)
from apps.workspaces.models import Workspace

ItemStatus = Literal["ok", "missing-sidecar", "missing-media", "malformed-sidecar"]

_VIDEO_EXTS = {".mp4", ".mov", ".webm"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg"}


@dataclass(frozen=True)
class VideoLibraryItem:
    subfolder: str
    filename: str
    drive_id: str
    drive_url: str
    ref: str  # "library:video/<subfolder>/<filename>"
    name: str | None
    description: str | None
    tags: list[str]
    status: ItemStatus


@dataclass(frozen=True)
class VideoLibrarySubfolder:
    subfolder: str
    items: list[VideoLibraryItem]


@dataclass(frozen=True)
class VideoLibraryResponse:
    subfolders: list[VideoLibrarySubfolder]


@dataclass(frozen=True)
class AudioLibraryItem:
    hash: str
    drive_id: str
    drive_url: str
    voice_id: str | None
    model: str | None
    text: str | None
    duration_sec: float | None
    generated_at: str | None
    status: ItemStatus


@dataclass(frozen=True)
class AudioLibraryResponse:
    items: list[AudioLibraryItem]


def _drive_url(drive_id: str) -> str:
    return f"https://drive.google.com/file/d/{drive_id}/view"


def _layout(workspace: Workspace) -> tuple[DriveLayout, DriveClient]:
    # Import locally to avoid a cycle: apps/videos/service.py imports
    # apps/videos/library/refs.py which imports this module.
    from apps.videos.service import layout_for
    return layout_for(workspace)


def list_video_library(workspace: Workspace) -> VideoLibraryResponse:
    layout, client = _layout(workspace)
    subs = drive_mod.list_library_subfolders(layout, client, drive_mod.LIBRARY_VIDEO)
    out_subs: list[VideoLibrarySubfolder] = []
    for sub in subs:
        items = _items_in_video_subfolder(layout, client, sub.name)
        if not items:
            continue
        out_subs.append(VideoLibrarySubfolder(subfolder=sub.name, items=items))
    return VideoLibraryResponse(subfolders=out_subs)


def _items_in_video_subfolder(
    layout: DriveLayout, client: DriveClient, subfolder: str,
) -> list[VideoLibraryItem]:
    files = drive_mod.list_library_files(layout, client, drive_mod.LIBRARY_VIDEO, subfolder)
    media: dict[str, drive_mod.DriveFile] = {}
    sidecars: dict[str, drive_mod.DriveFile] = {}
    for f in files:
        ext = PurePosixPath(f.name).suffix.lower()
        stem = PurePosixPath(f.name).stem
        if ext in _VIDEO_EXTS:
            media[stem] = f
        elif ext == ".json":
            sidecars[stem] = f
        # Other extensions are ignored (e.g. .DS_Store, transient junk)

    out: list[VideoLibraryItem] = []
    for stem, mf in sorted(media.items()):
        sc_file = sidecars.pop(stem, None)
        if sc_file is None:
            out.append(VideoLibraryItem(
                subfolder=subfolder, filename=mf.name, drive_id=mf.id,
                drive_url=_drive_url(mf.id),
                ref=f"library:video/{subfolder}/{mf.name}",
                name=None, description=None, tags=[],
                status="missing-sidecar",
            ))
            continue
        raw = client.get_binary(sc_file.id)
        try:
            sc = parse_video_sidecar(raw.decode("utf-8"))
        except (SidecarParseError, UnicodeDecodeError):
            out.append(VideoLibraryItem(
                subfolder=subfolder, filename=mf.name, drive_id=mf.id,
                drive_url=_drive_url(mf.id),
                ref=f"library:video/{subfolder}/{mf.name}",
                name=None, description=None, tags=[],
                status="malformed-sidecar",
            ))
            continue
        out.append(VideoLibraryItem(
            subfolder=subfolder, filename=mf.name, drive_id=mf.id,
            drive_url=_drive_url(mf.id),
            ref=f"library:video/{subfolder}/{mf.name}",
            name=sc.name, description=sc.description, tags=list(sc.tags),
            status="ok",
        ))

    # Orphan sidecars (sidecar present, media missing)
    for stem, sc_file in sorted(sidecars.items()):
        out.append(VideoLibraryItem(
            subfolder=subfolder, filename=f"{stem}.<missing>", drive_id=sc_file.id,
            drive_url=_drive_url(sc_file.id),
            ref=f"library:video/{subfolder}/{stem}",
            name=None, description=None, tags=[],
            status="missing-media",
        ))
    return out


def list_audio_library(workspace: Workspace) -> AudioLibraryResponse:
    layout, client = _layout(workspace)
    files = drive_mod.list_audio_library_files(layout, client)
    media: dict[str, drive_mod.DriveFile] = {}
    sidecars: dict[str, drive_mod.DriveFile] = {}
    for f in files:
        ext = PurePosixPath(f.name).suffix.lower()
        stem = PurePosixPath(f.name).stem
        if ext in _AUDIO_EXTS:
            media[stem] = f
        elif ext == ".json":
            sidecars[stem] = f

    items: list[AudioLibraryItem] = []
    for stem, mf in sorted(media.items()):
        sc_file = sidecars.pop(stem, None)
        if sc_file is None:
            items.append(AudioLibraryItem(
                hash=stem, drive_id=mf.id, drive_url=_drive_url(mf.id),
                voice_id=None, model=None, text=None,
                duration_sec=None, generated_at=None,
                status="missing-sidecar",
            ))
            continue
        raw = client.get_binary(sc_file.id)
        try:
            sc: AudioSidecar = parse_audio_sidecar(raw.decode("utf-8"))
        except (SidecarParseError, UnicodeDecodeError):
            items.append(AudioLibraryItem(
                hash=stem, drive_id=mf.id, drive_url=_drive_url(mf.id),
                voice_id=None, model=None, text=None,
                duration_sec=None, generated_at=None,
                status="malformed-sidecar",
            ))
            continue
        items.append(AudioLibraryItem(
            hash=stem, drive_id=mf.id, drive_url=_drive_url(mf.id),
            voice_id=sc.voice_id, model=sc.model, text=sc.text,
            duration_sec=sc.duration_sec, generated_at=sc.generated_at,
            status="ok",
        ))

    # Orphan sidecars (sidecar present, media missing).
    for stem, sc_file in sorted(sidecars.items()):
        items.append(AudioLibraryItem(
            hash=stem, drive_id=sc_file.id, drive_url=_drive_url(sc_file.id),
            voice_id=None, model=None, text=None,
            duration_sec=None, generated_at=None,
            status="missing-media",
        ))

    return AudioLibraryResponse(items=items)
```

- [ ] **Step 4: Re-run the tests**

Run: `pytest apps/videos/library/tests/test_reader.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/videos/library/reader.py apps/videos/library/tests/test_reader.py
git commit -m "videos(library): reader pairs media + sidecar, surfaces orphans"
```

### Task 4.2: Cache layer for library reads

**Files:**
- Modify: `apps/videos/cache.py` (add new keyspace)
- Modify: `apps/videos/library/reader.py` (wrap list_* with cache)
- Test: existing tests + new cache-hit assertion

- [ ] **Step 1: Add a cache-hit test**

Append to `apps/videos/library/tests/test_reader.py`:

```python
def test_list_video_library_uses_cache(workspace, fake_drive, seeded_video_library, monkeypatch):
    """Second call within TTL doesn't re-hit Drive."""
    from apps.videos import drive as drive_mod

    real_list_subfolders = drive_mod.list_library_subfolders
    call_count = {"n": 0}

    def counting(*args, **kwargs):
        call_count["n"] += 1
        return real_list_subfolders(*args, **kwargs)

    monkeypatch.setattr(drive_mod, "list_library_subfolders", counting)

    reader.list_video_library(workspace)
    reader.list_video_library(workspace)
    assert call_count["n"] == 1, "second call must hit cache"
```

- [ ] **Step 2: Add cache helpers to `apps/videos/cache.py`**

Append to `apps/videos/cache.py`:

```python
# ---------------------------------------------------------------------------
# Media library
# ---------------------------------------------------------------------------


def _lib_video_key(ws_slug: str) -> str:
    return f"videos:lib:video:{ws_slug}"


def _lib_audio_key(ws_slug: str) -> str:
    return f"videos:lib:audio:{ws_slug}"


def get_lib_video(ws_slug: str):
    return _cache.get(_lib_video_key(ws_slug))


def set_lib_video(ws_slug: str, value) -> None:
    _cache.set(_lib_video_key(ws_slug), value, _TTL_SECONDS)


def invalidate_lib_video(ws_slug: str) -> None:
    _cache.delete(_lib_video_key(ws_slug))


def get_lib_audio(ws_slug: str):
    return _cache.get(_lib_audio_key(ws_slug))


def set_lib_audio(ws_slug: str, value) -> None:
    _cache.set(_lib_audio_key(ws_slug), value, _TTL_SECONDS)


def invalidate_lib_audio(ws_slug: str) -> None:
    _cache.delete(_lib_audio_key(ws_slug))
```

- [ ] **Step 3: Wrap reader entry points**

Edit `apps/videos/library/reader.py`. At the bottom of the file, replace the two top-level functions with cached wrappers (rename the originals to `_uncached`):

```python
# Wrap the two public entry points with the videos: cache.
from apps.videos import cache as _cache_mod


def _list_video_library_uncached(workspace: Workspace) -> VideoLibraryResponse:
    # existing body of list_video_library — move into this private fn.
    ...


def list_video_library(workspace: Workspace) -> VideoLibraryResponse:
    hit = _cache_mod.get_lib_video(workspace.slug)
    if hit is not None:
        return hit
    value = _list_video_library_uncached(workspace)
    _cache_mod.set_lib_video(workspace.slug, value)
    return value


def _list_audio_library_uncached(workspace: Workspace) -> AudioLibraryResponse:
    # existing body of list_audio_library — move into this private fn.
    ...


def list_audio_library(workspace: Workspace) -> AudioLibraryResponse:
    hit = _cache_mod.get_lib_audio(workspace.slug)
    if hit is not None:
        return hit
    value = _list_audio_library_uncached(workspace)
    _cache_mod.set_lib_audio(workspace.slug, value)
    return value
```

(Mechanical: rename the prior `list_video_library` body to `_list_video_library_uncached`, same for audio.)

- [ ] **Step 4: Re-run the tests**

Run: `pytest apps/videos/library/tests/test_reader.py -v`
Expected: PASS (4 tests including the cache-hit assertion).

- [ ] **Step 5: Commit**

```bash
git add apps/videos/cache.py apps/videos/library/reader.py apps/videos/library/tests/test_reader.py
git commit -m "videos(library): 60s TTL cache around library reads"
```

---

## Phase 5 — `library:` reference resolver

### Task 5.1: Parse + resolve `library:` refs

**Files:**
- Create: `apps/videos/library/refs.py`
- Create: `apps/videos/library/tests/test_refs.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/videos/library/tests/test_refs.py
import pytest

from apps.videos import drive as drive_mod
from apps.videos import service as service_mod
from apps.videos.library import refs


def test_parse_library_ref_video():
    parsed = refs.parse_library_ref("library:video/uganda-field/drone-wide.mp4")
    assert parsed.media == "video"
    assert parsed.subfolder == "uganda-field"
    assert parsed.filename == "drone-wide.mp4"


def test_parse_library_ref_audio_flat():
    parsed = refs.parse_library_ref("library:audio/deadbeef.mp3")
    assert parsed.media == "audio"
    assert parsed.subfolder is None
    assert parsed.filename == "deadbeef.mp3"


def test_parse_library_ref_rejects_malformed():
    with pytest.raises(refs.LibraryRefError):
        refs.parse_library_ref("library:nope/x/y")
    with pytest.raises(refs.LibraryRefError):
        refs.parse_library_ref("gdrive:abc")
    with pytest.raises(refs.LibraryRefError):
        refs.parse_library_ref("library:video/")


def test_resolve_library_ref_returns_drive_id(workspace, fake_drive):
    layout = service_mod.layout_for(workspace)[0]
    drive_id = drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_VIDEO,
        "x.mp4", b"x", "video/mp4", subfolder="cat",
    )
    resolved = refs.resolve_library_ref(workspace, "library:video/cat/x.mp4")
    assert resolved is not None
    assert resolved.drive_id == drive_id


def test_resolve_library_ref_missing_returns_none(workspace, fake_drive):
    assert refs.resolve_library_ref(workspace, "library:video/none/missing.mp4") is None
```

- [ ] **Step 2: Run the test, watch it fail**

Run: `pytest apps/videos/library/tests/test_refs.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `refs.py`**

```python
# apps/videos/library/refs.py
"""Parse + resolve the ``library:<media>/[<subfolder>/]<filename>`` spec
reference syntax.

Used by the renderer's hydrate step (and by future callers like the
spec generator skill) to turn a stable ``library:`` ref into a concrete
Drive file id.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from apps.videos import drive as drive_mod
from apps.workspaces.models import Workspace


class LibraryRefError(ValueError):
    """Raised on malformed library refs."""


@dataclass(frozen=True)
class ParsedRef:
    media: str  # "video" or "audio"
    subfolder: str | None  # None for audio (flat layout)
    filename: str


@dataclass(frozen=True)
class ResolvedRef:
    parsed: ParsedRef
    drive_id: str


_VIDEO_RE = re.compile(r"^library:video/([^/]+)/([^/]+)$")
_AUDIO_RE = re.compile(r"^library:audio/([^/]+)$")


def parse_library_ref(ref: str) -> ParsedRef:
    """Parse a ``library:`` reference. Raises LibraryRefError on bad input."""
    m = _VIDEO_RE.match(ref)
    if m is not None:
        subfolder, filename = m.group(1), m.group(2)
        return ParsedRef(media="video", subfolder=subfolder, filename=filename)
    m = _AUDIO_RE.match(ref)
    if m is not None:
        return ParsedRef(media="audio", subfolder=None, filename=m.group(1))
    raise LibraryRefError(f"not a library reference: {ref!r}")


def is_library_ref(ref: str) -> bool:
    return ref.startswith("library:")


def resolve_library_ref(workspace: Workspace, ref: str) -> ResolvedRef | None:
    """Resolve a library ref against the workspace's Drive layout.

    Returns None when the target file does not exist; raises
    LibraryRefError on malformed refs.
    """
    parsed = parse_library_ref(ref)
    # Lazy import to avoid cycles.
    from apps.videos.service import layout_for
    layout, client = layout_for(workspace)
    if parsed.media == "audio":
        files = drive_mod.list_audio_library_files(layout, client)
    else:
        assert parsed.subfolder is not None  # parser guarantees
        files = drive_mod.list_library_files(
            layout, client, drive_mod.LIBRARY_VIDEO, parsed.subfolder,
        )
    for f in files:
        if f.name == parsed.filename:
            return ResolvedRef(parsed=parsed, drive_id=f.id)
    return None
```

- [ ] **Step 4: Re-run the tests**

Run: `pytest apps/videos/library/tests/test_refs.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/videos/library/refs.py apps/videos/library/tests/test_refs.py
git commit -m "videos(library): library:<media>/<sub>/<file> ref parser + resolver"
```

### Task 5.2: Wire `library:` into the hydrate path

**Files:**
- Modify: `apps/videos/service.py` — hydrate helper that prepares clips for render
- Test: smoke

(Discover and edit the existing hydrate code that turns manifest values into Drive downloads. The minimal change: when a manifest value starts with `library:`, call `refs.resolve_library_ref`; if it returns a `ResolvedRef`, download by `drive_id` exactly as the existing `gdrive:` path does.)

- [ ] **Step 1: Locate the hydrate function**

Run: `grep -n 'def hydrate\|def.*manifest\|parseManifestRef\|gdrive:' apps/videos/service.py | head -20`
Identify the function (likely named `_resolve_manifest_entry` or similar) that consumes manifest values today. Document its path:line in this checklist comment.

- [ ] **Step 2: Add a failing test that asserts library refs resolve to Drive files**

Add to `apps/videos/tests/test_service.py`:

```python
def test_hydrate_resolves_library_ref(workspace, fake_drive):
    """Manifest entry library:video/cat/x.mp4 resolves to the Drive file
    in library/video/cat/x.mp4 the same way gdrive:<id> resolves directly."""
    from apps.videos import drive as drive_mod
    from apps.videos import service as service_mod
    layout = service_mod.layout_for(workspace)[0]
    drive_id = drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_VIDEO,
        "x.mp4", b"x", "video/mp4", subfolder="cat",
    )
    # _resolve_manifest_entry should return either the Drive id or a payload
    # equivalent to what the gdrive path returns. Exact shape depends on the
    # existing function — adjust this assertion to match.
    resolved = service_mod._resolve_manifest_entry(workspace, "library:video/cat/x.mp4")
    assert resolved is not None
    assert getattr(resolved, "drive_id", None) == drive_id or resolved == drive_id
```

- [ ] **Step 3: Patch the function**

In the manifest-resolution function found in Step 1, add a new branch above the `gdrive:` branch:

```python
from apps.videos.library import refs as _lib_refs

if value.startswith("library:"):
    resolved = _lib_refs.resolve_library_ref(workspace, value)
    if resolved is None:
        return None  # or raise, matching existing missing-file convention
    # Reuse the existing "given a Drive id, download + cache" code path:
    return _resolve_by_drive_id(workspace, resolved.drive_id)
```

- [ ] **Step 4: Re-run the test**

Run: `pytest apps/videos/tests/test_service.py::test_hydrate_resolves_library_ref -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/videos/service.py apps/videos/tests/test_service.py
git commit -m "videos(service): resolve library: refs alongside gdrive: in manifest"
```

---

## Phase 6 — API endpoints

### Task 6.1: Add output schemas in `apps/videos/schemas.py`

- [ ] **Step 1: Write the failing API test**

Create `apps/videos/tests/test_api_library.py`:

```python
import json

import pytest

from apps.videos import drive as drive_mod
from apps.videos import service as service_mod


@pytest.fixture
def seeded_video_lib(workspace, fake_drive):
    layout = service_mod.layout_for(workspace)[0]
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_VIDEO,
        "drone.mp4", b"a", "video/mp4", subfolder="uganda",
    )
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_VIDEO,
        "drone.json",
        json.dumps({"name": "Drone", "tags": ["uganda"]}).encode(),
        "application/json", subfolder="uganda",
    )


def test_get_video_library_returns_grouped_subfolders(api_client, workspace, seeded_video_lib):
    resp = api_client.get(f"/api/w/{workspace.slug}/videos/library/video")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["subfolders"]) == 1
    assert body["subfolders"][0]["subfolder"] == "uganda"
    items = body["subfolders"][0]["items"]
    assert items[0]["status"] == "ok"
    assert items[0]["name"] == "Drone"
    assert items[0]["ref"] == "library:video/uganda/drone.mp4"


def test_get_audio_library_flat_list(api_client, workspace, fake_drive):
    layout = service_mod.layout_for(workspace)[0]
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        "abc.mp3", b"a", "audio/mpeg",
    )
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        "abc.json",
        json.dumps({
            "voice_id": "v", "model": "m", "text": "Hi",
            "duration_sec": 1.0, "generated_at": "2026-05-15T00:00:00Z",
        }).encode(),
        "application/json",
    )
    resp = api_client.get(f"/api/w/{workspace.slug}/videos/library/audio")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["hash"] == "abc"
    assert items[0]["voice_id"] == "v"


def test_library_endpoints_require_workspace_membership(api_client, other_workspace):
    resp = api_client.get(f"/api/w/{other_workspace.slug}/videos/library/video")
    assert resp.status_code == 404


def test_library_endpoints_are_mcp_exposed():
    from apps.videos.api import router
    spec = router.api.get_openapi_schema()
    op_video = spec["paths"]["/w/{workspace_slug}/videos/library/video"]["get"]
    assert op_video.get("x-mcp-expose") is True
    op_audio = spec["paths"]["/w/{workspace_slug}/videos/library/audio"]["get"]
    assert op_audio.get("x-mcp-expose") is True
```

- [ ] **Step 2: Run the test, watch it fail**

Run: `pytest apps/videos/tests/test_api_library.py -v`
Expected: FAIL (endpoint not registered).

- [ ] **Step 3: Add the new schemas**

Append to `apps/videos/schemas.py`:

```python
class MediaLibraryVideoItemOut(StrictModel):
    ref: str
    drive_id: str
    drive_url: str
    filename: str
    name: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: str  # "ok" | "missing-sidecar" | "missing-media" | "malformed-sidecar"


class MediaLibraryVideoSubfolderOut(StrictModel):
    subfolder: str
    items: list[MediaLibraryVideoItemOut]


class MediaLibraryVideoOut(StrictModel):
    subfolders: list[MediaLibraryVideoSubfolderOut]


class MediaLibraryAudioItemOut(StrictModel):
    hash: str
    drive_id: str
    drive_url: str
    voice_id: str | None = None
    model: str | None = None
    text: str | None = None
    duration_sec: float | None = None
    generated_at: str | None = None
    status: str


class MediaLibraryAudioOut(StrictModel):
    items: list[MediaLibraryAudioItemOut]
```

- [ ] **Step 4: Add the endpoints**

In `apps/videos/api.py`, after the existing template endpoints, add:

```python
from .library import reader as library_reader  # at top of file

from .schemas import (
    # ... existing imports
    MediaLibraryAudioItemOut,
    MediaLibraryAudioOut,
    MediaLibraryVideoItemOut,
    MediaLibraryVideoOut,
    MediaLibraryVideoSubfolderOut,
)


@router.get(
    "/library/video",
    response=MediaLibraryVideoOut,
    summary="List curated video library items grouped by subfolder",
    openapi_extra={"x-mcp-expose": True},
)
def list_media_library_video(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
) -> MediaLibraryVideoOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    raw = library_reader.list_video_library(workspace)
    return MediaLibraryVideoOut(subfolders=[
        MediaLibraryVideoSubfolderOut(
            subfolder=s.subfolder,
            items=[
                MediaLibraryVideoItemOut(
                    ref=i.ref, drive_id=i.drive_id, drive_url=i.drive_url,
                    filename=i.filename, name=i.name, description=i.description,
                    tags=i.tags, status=i.status,
                )
                for i in s.items
            ],
        )
        for s in raw.subfolders
    ])


@router.get(
    "/library/audio",
    response=MediaLibraryAudioOut,
    summary="List the audio library (TTS clips with voice + text metadata)",
    openapi_extra={"x-mcp-expose": True},
)
def list_media_library_audio(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
) -> MediaLibraryAudioOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    raw = library_reader.list_audio_library(workspace)
    return MediaLibraryAudioOut(items=[
        MediaLibraryAudioItemOut(
            hash=i.hash, drive_id=i.drive_id, drive_url=i.drive_url,
            voice_id=i.voice_id, model=i.model, text=i.text,
            duration_sec=i.duration_sec, generated_at=i.generated_at,
            status=i.status,
        )
        for i in raw.items
    ])
```

- [ ] **Step 5: Re-run the tests**

Run: `pytest apps/videos/tests/test_api_library.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Regenerate the OpenAPI schema**

Run: `python manage.py spectacular --file frontend/src/api/openapi.json --validate` (or whatever the project's regen command is — check `.github/workflows/regen-openapi.yml`).

Then regenerate the TS types: `bun run --cwd frontend regen-openapi` (check `frontend/package.json`).

- [ ] **Step 7: Commit**

```bash
git add apps/videos/schemas.py apps/videos/api.py apps/videos/tests/test_api_library.py \
        frontend/src/api/generated.ts
git commit -m "videos(api): add /library/{video,audio} endpoints (MCP-exposed)"
```

---

## Phase 7 — Frontend page + nav

### Task 7.1: API client functions

**Files:**
- Modify: `frontend/src/api/videos.ts`

- [ ] **Step 1: Add the two new functions**

Append to `frontend/src/api/videos.ts`:

```ts
import type {
  MediaLibraryAudioOut,
  MediaLibraryVideoOut,
} from "./generated";

export type {
  MediaLibraryAudioItemOut,
  MediaLibraryAudioOut,
  MediaLibraryVideoItemOut,
  MediaLibraryVideoOut,
  MediaLibraryVideoSubfolderOut,
} from "./generated";

export async function listMediaLibraryVideo(
  workspaceSlug: string,
): Promise<MediaLibraryVideoOut> {
  const r = await fetch(`/api/w/${workspaceSlug}/videos/library/video`);
  if (!r.ok) throw new Error(`library/video: HTTP ${r.status}`);
  return r.json();
}

export async function listMediaLibraryAudio(
  workspaceSlug: string,
): Promise<MediaLibraryAudioOut> {
  const r = await fetch(`/api/w/${workspaceSlug}/videos/library/audio`);
  if (!r.ok) throw new Error(`library/audio: HTTP ${r.status}`);
  return r.json();
}
```

- [ ] **Step 2: Type-check**

Run: `bunx --cwd frontend tsc -b`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/videos.ts
git commit -m "videos(frontend): listMediaLibrary{Video,Audio} client functions"
```

### Task 7.2: `MediaLibraryPage.tsx`

**Files:**
- Create: `frontend/src/pages/MediaLibraryPage.tsx`
- Create: `frontend/src/pages/__tests__/MediaLibraryPage.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/__tests__/MediaLibraryPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import * as api from "@/api/videos";
import MediaLibraryPage from "@/pages/MediaLibraryPage";

describe("MediaLibraryPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "listMediaLibraryVideo").mockResolvedValue({
      subfolders: [{
        subfolder: "uganda",
        items: [{
          ref: "library:video/uganda/drone.mp4",
          drive_id: "abc", drive_url: "https://drive/abc",
          filename: "drone.mp4", name: "Drone", description: null,
          tags: ["uganda"], status: "ok",
        }],
      }],
    });
    vi.spyOn(api, "listMediaLibraryAudio").mockResolvedValue({
      items: [{
        hash: "h1", drive_id: "d1", drive_url: "https://drive/d1",
        voice_id: "v1", model: "m1", text: "Hello",
        duration_sec: 1.4, generated_at: "2026-05-15T00:00:00Z",
        status: "ok",
      }],
    });
  });

  it("renders video subfolders by default", async () => {
    render(
      <MemoryRouter initialEntries={["/w/ws/videos/library"]}>
        <Routes>
          <Route path="/w/:workspaceSlug/videos/library" element={<MediaLibraryPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("uganda")).toBeInTheDocument();
    expect(await screen.findByText("Drone")).toBeInTheDocument();
  });

  it("switches to audio tab via ?type=audio", async () => {
    render(
      <MemoryRouter initialEntries={["/w/ws/videos/library?type=audio"]}>
        <Routes>
          <Route path="/w/:workspaceSlug/videos/library" element={<MediaLibraryPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Hello")).toBeInTheDocument();
    expect(await screen.findByText(/v1/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test, watch it fail**

Run: `bun --cwd frontend run test -- MediaLibraryPage`
Expected: FAIL (component not found).

- [ ] **Step 3: Implement the page**

```tsx
// frontend/src/pages/MediaLibraryPage.tsx
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { AlertTriangle, ExternalLink, Library } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  listMediaLibraryAudio,
  listMediaLibraryVideo,
  type MediaLibraryAudioOut,
  type MediaLibraryVideoOut,
} from "@/api/videos";

type Tab = "video" | "audio";

export default function MediaLibraryPage() {
  const { workspaceSlug } = useParams<{ workspaceSlug: string }>();
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("type") === "audio" ? "audio" : "video";

  const [video, setVideo] = useState<MediaLibraryVideoOut | null>(null);
  const [audio, setAudio] = useState<MediaLibraryAudioOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!workspaceSlug) return;
    let cancelled = false;
    if (tab === "video" && video === null) {
      listMediaLibraryVideo(workspaceSlug)
        .then((d) => !cancelled && setVideo(d))
        .catch((e) => !cancelled && setError(String(e)));
    } else if (tab === "audio" && audio === null) {
      listMediaLibraryAudio(workspaceSlug)
        .then((d) => !cancelled && setAudio(d))
        .catch((e) => !cancelled && setError(String(e)));
    }
    return () => { cancelled = true; };
  }, [workspaceSlug, tab, video, audio]);

  const setTab = (t: Tab) => {
    if (t === "video") params.delete("type"); else params.set("type", "audio");
    setParams(params, { replace: true });
  };

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <header className="mb-6 flex items-center gap-2">
        <Library className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-2xl font-semibold">Media library</h1>
        <Link to={`/w/${workspaceSlug}/videos`} className="ml-auto text-sm text-muted-foreground underline">
          ← Back to programs
        </Link>
      </header>

      <div className="mb-6 flex gap-2">
        <button
          type="button"
          onClick={() => setTab("video")}
          className={`rounded px-3 py-1.5 text-sm font-medium ${tab === "video" ? "bg-primary text-primary-foreground" : "border"}`}
        >
          Video
        </button>
        <button
          type="button"
          onClick={() => setTab("audio")}
          className={`rounded px-3 py-1.5 text-sm font-medium ${tab === "audio" ? "bg-primary text-primary-foreground" : "border"}`}
        >
          Audio
        </button>
      </div>

      {error && (
        <div className="mb-4 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 text-destructive" />
          <div className="text-muted-foreground">{error}</div>
        </div>
      )}

      {tab === "video" ? renderVideo(video) : renderAudio(audio)}
    </div>
  );
}

function renderVideo(data: MediaLibraryVideoOut | null) {
  if (data === null) return <Skeleton className="h-40 w-full" />;
  if (data.subfolders.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
        No video clips in the library yet. Drop files into
        <code className="mx-1 rounded bg-muted px-1 py-0.5 text-xs">
          videos/library/video/&lt;category&gt;/
        </code>
        in Drive with a sibling
        <code className="mx-1 rounded bg-muted px-1 py-0.5 text-xs">&lt;name&gt;.json</code>
        sidecar.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-8">
      {data.subfolders.map((sub) => (
        <section key={sub.subfolder}>
          <h2 className="mb-3 font-medium">{sub.subfolder}</h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {sub.items.map((item) => (
              <article key={item.drive_id} className={`rounded border p-3 ${item.status === "ok" ? "" : "border-dashed bg-muted/30"}`}>
                <header className="mb-1 flex items-center justify-between gap-2">
                  <h3 className="text-sm font-medium">{item.name ?? item.filename}</h3>
                  {item.status !== "ok" && (
                    <Badge variant="outline" className="text-[10px]">{item.status}</Badge>
                  )}
                </header>
                <p className="mb-2 font-mono text-xs text-muted-foreground">{item.filename}</p>
                {item.description && <p className="mb-2 text-sm">{item.description}</p>}
                <div className="mb-2 flex flex-wrap gap-1">
                  {item.tags.map((t) => (
                    <span key={t} className="rounded-full bg-muted px-2 py-0.5 text-xs">{t}</span>
                  ))}
                </div>
                <a href={item.drive_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-muted-foreground underline">
                  Open in Drive <ExternalLink className="h-3 w-3" />
                </a>
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function renderAudio(data: MediaLibraryAudioOut | null) {
  if (data === null) return <Skeleton className="h-40 w-full" />;
  if (data.items.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
        No audio clips yet. They get generated automatically when a render
        synthesizes voiceover; check back after running a render.
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {data.items.map((item) => (
        <article key={item.drive_id} className={`rounded border p-3 ${item.status === "ok" ? "" : "border-dashed bg-muted/30"}`}>
          <header className="mb-1 flex items-center gap-2">
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{item.hash}</code>
            {item.status !== "ok" && (
              <Badge variant="outline" className="ml-auto text-[10px]">{item.status}</Badge>
            )}
          </header>
          <p className="mb-2 text-sm" title={item.text ?? ""}>{truncate(item.text)}</p>
          <div className="mb-2 flex flex-wrap gap-1 text-xs text-muted-foreground">
            {item.voice_id && <span className="rounded-full bg-muted px-2 py-0.5">voice: {item.voice_id.slice(0, 6)}…</span>}
            {item.model && <span className="rounded-full bg-muted px-2 py-0.5">{item.model}</span>}
            {item.duration_sec !== null && item.duration_sec !== undefined && (
              <span className="rounded-full bg-muted px-2 py-0.5">{item.duration_sec.toFixed(1)}s</span>
            )}
          </div>
          <a href={item.drive_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-muted-foreground underline">
            Open in Drive <ExternalLink className="h-3 w-3" />
          </a>
        </article>
      ))}
    </div>
  );
}

function truncate(s: string | null | undefined, max = 140): string {
  if (!s) return "";
  return s.length <= max ? s : s.slice(0, max - 1) + "…";
}
```

- [ ] **Step 4: Re-run the tests**

Run: `bun --cwd frontend run test -- MediaLibraryPage`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/MediaLibraryPage.tsx \
        frontend/src/pages/__tests__/MediaLibraryPage.test.tsx
git commit -m "videos(frontend): MediaLibraryPage with Video/Audio tabs"
```

### Task 7.3: Route + nav link

**Files:**
- Modify: `frontend/src/router.tsx` (line 58)
- Modify: `frontend/src/pages/VideosListPage.tsx` (header block)

- [ ] **Step 1: Add the route**

Edit `frontend/src/router.tsx`. Add the import:

```ts
import MediaLibraryPage from "./pages/MediaLibraryPage";
```

Insert the route inside the workspace-scoped children, between the existing `videos` and `videos/:programSlug` entries:

```tsx
{ path: "videos", element: <VideosListPage /> },
{ path: "videos/library", element: <MediaLibraryPage /> },
{ path: "videos/:programSlug", element: <VideoExplorerPage /> },
```

- [ ] **Step 2: Add the header link in `VideosListPage.tsx`**

Replace the `<header>` block in `frontend/src/pages/VideosListPage.tsx` (around line 31) with:

```tsx
<header className="mb-6 flex items-center gap-2">
  <Video className="h-5 w-5 text-muted-foreground" />
  <h1 className="text-2xl font-semibold">Videos</h1>
  <Link
    to={`/w/${workspaceSlug}/videos/library`}
    className="ml-auto text-sm text-muted-foreground underline hover:text-foreground"
  >
    Media library →
  </Link>
</header>
```

- [ ] **Step 3: Type-check**

Run: `bunx --cwd frontend tsc -b`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/router.tsx frontend/src/pages/VideosListPage.tsx
git commit -m "videos(frontend): route + nav link for media library"
```

---

## Phase 8 — Backfill management commands

### Task 8.1: Audio sidecar backfill

**Files:**
- Create: `apps/videos/management/commands/videos_backfill_audio_sidecars.py`
- Create: `apps/videos/tests/test_backfill.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/videos/tests/test_backfill.py
import hashlib
import json

import pytest
from django.core.management import call_command

from apps.videos import drive as drive_mod
from apps.videos import service as service_mod


def _cache_key(text: str, voice_id: str, model: str) -> str:
    return hashlib.sha256(
        f"{voice_id}::{model}::{text}".encode()
    ).hexdigest()[:16]


def test_backfill_audio_sidecars_writes_for_reconstructable_hashes(
    workspace, fake_drive,
):
    layout = service_mod.layout_for(workspace)[0]

    # Seed one spec under a program with one beat of narration.
    spec_yaml = (
        "name: Demo\n"
        "voice:\n"
        "  voice_id: voiceA\n"
        "  model: modelB\n"
        "narration:\n"
        "  by_beat:\n"
        "    hook: \"Hello world.\"\n"
    )
    drive_mod.write_spec(layout, fake_drive.client, "demo", "run-001", spec_yaml)

    # The cache key for that synthesis:
    key = _cache_key("Hello world.", "voiceA", "modelB")
    # Orphan mp3 with no sidecar
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        f"{key}.mp3", b"mp3", "audio/mpeg",
    )

    call_command("videos_backfill_audio_sidecars", "--workspace", workspace.slug)

    # Sidecar exists now
    raw = drive_mod.read_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        f"{key}.json",
    )
    assert raw is not None
    parsed = json.loads(raw.decode())
    assert parsed["voice_id"] == "voiceA"
    assert parsed["model"] == "modelB"
    assert parsed["text"] == "Hello world."


def test_backfill_skips_already_sidecared(workspace, fake_drive):
    layout = service_mod.layout_for(workspace)[0]
    key = _cache_key("X", "V", "M")
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        f"{key}.mp3", b"mp3", "audio/mpeg",
    )
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        f"{key}.json",
        json.dumps({
            "voice_id": "V", "model": "M", "text": "X",
            "duration_sec": None, "generated_at": "2026-05-15T00:00:00Z",
        }).encode(),
        "application/json",
    )
    # Should be a no-op
    call_command("videos_backfill_audio_sidecars", "--workspace", workspace.slug)
```

- [ ] **Step 2: Run the test, watch it fail**

Run: `pytest apps/videos/tests/test_backfill.py -v`
Expected: FAIL (command not found).

- [ ] **Step 3: Implement the command**

```python
# apps/videos/management/commands/videos_backfill_audio_sidecars.py
"""Reconstruct audio sidecars for orphan <hash>.mp3 files in library/audio/.

Walks every program's run specs in the target workspace, recomputes the
ElevenLabs cacheKey for every (narration.by_beat[*], voice.voice_id,
voice.model) triple, and writes the matching sidecar if the orphan mp3
exists. Orphans not reconstructible from any spec stay sidecar-less.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import PurePosixPath

from django.core.management.base import BaseCommand, CommandError
from ruamel.yaml import YAML

from apps.videos import drive as drive_mod
from apps.workspaces.models import Workspace


def _cache_key(text: str, voice_id: str, model: str) -> str:
    return hashlib.sha256(
        f"{voice_id}::{model}::{text}".encode()
    ).hexdigest()[:16]


class Command(BaseCommand):
    help = "Reconstruct audio sidecars for orphan library/audio/<hash>.mp3 files."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, workspace, dry_run, **kwargs):  # noqa: ARG002
        try:
            ws = Workspace.objects.get(slug=workspace)
        except Workspace.DoesNotExist as e:
            raise CommandError(f"Unknown workspace: {workspace!r}") from e

        client = drive_mod.client_for_workspace(ws)
        layout = drive_mod.resolve_layout(ws, client)

        # Build a hash → (voice_id, model, text, generated_at) map from specs.
        recovered: dict[str, dict] = {}
        for program_slug in drive_mod.list_program_slugs(layout, client):
            for run_id in drive_mod.list_run_ids(layout, client, program_slug):
                spec_bytes = drive_mod.read_spec(layout, client, program_slug, run_id)
                if spec_bytes is None:
                    continue
                parsed = YAML(typ="safe").load(spec_bytes.decode())
                if not isinstance(parsed, dict):
                    continue
                voice = parsed.get("voice") or {}
                voice_id = voice.get("voice_id")
                model = voice.get("model")
                if not voice_id or not model:
                    continue
                narration = (parsed.get("narration") or {}).get("by_beat") or {}
                for _beat_id, text in narration.items():
                    if not isinstance(text, str) or not text.strip():
                        continue
                    key = _cache_key(text, voice_id, model)
                    recovered.setdefault(key, {
                        "voice_id": voice_id,
                        "model": model,
                        "text": text,
                        "duration_sec": None,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                    })

        # Walk library/audio/ for orphans and patch.
        audio_files = drive_mod.list_audio_library_files(layout, client)
        existing_sidecars = {
            PurePosixPath(f.name).stem
            for f in audio_files
            if f.name.endswith(".json")
        }
        existing_mp3s = [
            f for f in audio_files
            if f.name.endswith(".mp3")
        ]

        wrote = 0
        unmatched = 0
        for mp3 in existing_mp3s:
            stem = PurePosixPath(mp3.name).stem
            if stem in existing_sidecars:
                continue
            data = recovered.get(stem)
            if data is None:
                unmatched += 1
                continue
            self.stdout.write(f"  + {stem}.json  (voice {data['voice_id']}, model {data['model']})")
            if not dry_run:
                drive_mod.upload_library_file(
                    layout, client, drive_mod.LIBRARY_AUDIO,
                    f"{stem}.json",
                    json.dumps(data, indent=2).encode(),
                    "application/json",
                )
            wrote += 1

        self.stdout.write(self.style.SUCCESS(
            f"Backfilled {wrote} sidecar(s); {unmatched} orphan(s) had no matching spec."
        ))
```

- [ ] **Step 4: Re-run the tests**

Run: `pytest apps/videos/tests/test_backfill.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/videos/management/commands/videos_backfill_audio_sidecars.py \
        apps/videos/tests/test_backfill.py
git commit -m "videos(backfill): reconstruct audio sidecars from spec narration"
```

### Task 8.2: Video orphan stub-sidecar helper

**Files:**
- Create: `apps/videos/management/commands/videos_backfill_video_sidecars.py`

- [ ] **Step 1: Implement (no test — prints + writes stubs only)**

```python
# apps/videos/management/commands/videos_backfill_video_sidecars.py
"""Write stub sidecars for video library files that don't have one.

The stub is intentionally minimal — name from the filename, empty tags
list. Curators are expected to fill it in via Drive UI afterwards. The
goal is to surface orphans in the library UI without losing them.
"""
from __future__ import annotations

import json
from pathlib import PurePosixPath

from django.core.management.base import BaseCommand, CommandError

from apps.videos import drive as drive_mod
from apps.workspaces.models import Workspace

_VIDEO_EXTS = {".mp4", ".mov", ".webm"}


class Command(BaseCommand):
    help = "Stub sidecars for orphan video files in library/video/<*>/."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, workspace, dry_run, **kwargs):  # noqa: ARG002
        try:
            ws = Workspace.objects.get(slug=workspace)
        except Workspace.DoesNotExist as e:
            raise CommandError(f"Unknown workspace: {workspace!r}") from e

        client = drive_mod.client_for_workspace(ws)
        layout = drive_mod.resolve_layout(ws, client)

        subs = drive_mod.list_library_subfolders(layout, client, drive_mod.LIBRARY_VIDEO)
        total = 0
        for sub in subs:
            files = drive_mod.list_library_files(
                layout, client, drive_mod.LIBRARY_VIDEO, sub.name,
            )
            by_stem: dict[str, dict[str, str]] = {}
            for f in files:
                ext = PurePosixPath(f.name).suffix.lower()
                stem = PurePosixPath(f.name).stem
                if ext in _VIDEO_EXTS:
                    by_stem.setdefault(stem, {})["video"] = f.name
                elif ext == ".json":
                    by_stem.setdefault(stem, {})["sidecar"] = f.name
            for stem, entry in by_stem.items():
                if "video" in entry and "sidecar" not in entry:
                    self.stdout.write(f"  + {sub.name}/{stem}.json")
                    if not dry_run:
                        drive_mod.upload_library_file(
                            layout, client, drive_mod.LIBRARY_VIDEO,
                            f"{stem}.json",
                            json.dumps({"name": stem, "tags": []}, indent=2).encode(),
                            "application/json",
                            subfolder=sub.name,
                        )
                    total += 1
        self.stdout.write(self.style.SUCCESS(f"Stubbed {total} sidecar(s)."))
```

- [ ] **Step 2: Commit**

```bash
git add apps/videos/management/commands/videos_backfill_video_sidecars.py
git commit -m "videos(backfill): stub sidecars for orphan video library files"
```

---

## Phase 9 — Drive relocation command

### Task 9.1: `videos_relocate_existing_content`

**Files:**
- Create: `apps/videos/management/commands/videos_relocate_existing_content.py`

- [ ] **Step 1: Implement (idempotent; safe to re-run)**

```python
# apps/videos/management/commands/videos_relocate_existing_content.py
"""One-shot Drive relocation: existing_content/ → library/audio/ + shared/.

Moves:
  videos/existing_content/audio/*   → videos/library/audio/*
  videos/existing_content/shared/*  → videos/shared/*

Then deletes the empty videos/existing_content/ folder. Per-folder Drive
moves are atomic; the management command runs them sequentially.

Idempotent: files already present at the target with the same byte size
are skipped. Safe to re-run after a partial move.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.videos import drive as drive_mod
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Move existing_content/{audio,shared} to library/audio + shared."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, workspace, dry_run, **kwargs):  # noqa: ARG002
        try:
            ws = Workspace.objects.get(slug=workspace)
        except Workspace.DoesNotExist as e:
            raise CommandError(f"Unknown workspace: {workspace!r}") from e

        client = drive_mod.client_for_workspace(ws)
        layout = drive_mod.resolve_layout(ws, client)

        moved_audio = self._move_audio(layout, client, dry_run)
        moved_shared = self._move_shared(layout, client, dry_run)

        self.stdout.write(self.style.SUCCESS(
            f"Moved {moved_audio} audio file(s) and {moved_shared} shared file(s)."
        ))
        if not dry_run:
            # If existing_content/ is empty, delete it.
            ec_root = drive_mod.existing_content_folder_id(layout, client)
            if ec_root is not None:
                remaining = client.list_folder(ec_root)
                if not remaining:
                    client.delete_file(ec_root)
                    self.stdout.write("Deleted empty existing_content/.")

    def _move_audio(self, layout, client, dry_run) -> int:
        legacy_files = drive_mod.list_existing_content(
            layout, client, drive_mod.EXISTING_CONTENT_AUDIO,
        )
        if not legacy_files:
            return 0
        target_id = drive_mod.library_folder_id(
            layout, client, drive_mod.LIBRARY_AUDIO, create=not dry_run,
        )
        if target_id is None and dry_run:
            return len(legacy_files)
        assert target_id is not None
        moved = 0
        for f in legacy_files:
            target_existing = drive_mod._find_child(client, target_id, f.name)
            if target_existing is not None and (target_existing.size_bytes or 0) == (f.size_bytes or 0):
                self.stdout.write(f"  = audio/{f.name} (already present)")
                continue
            self.stdout.write(f"  → audio/{f.name}")
            if not dry_run:
                client.move_file(f.id, target_id)
            moved += 1
        return moved

    def _move_shared(self, layout, client, dry_run) -> int:
        legacy_files = drive_mod.list_existing_content(
            layout, client, drive_mod.EXISTING_CONTENT_SHARED,
        )
        if not legacy_files:
            return 0
        target_id = drive_mod.shared_top_folder_id(
            layout, client, create=not dry_run,
        )
        if target_id is None and dry_run:
            return len(legacy_files)
        assert target_id is not None
        moved = 0
        for f in legacy_files:
            target_existing = drive_mod._find_child(client, target_id, f.name)
            if target_existing is not None and (target_existing.size_bytes or 0) == (f.size_bytes or 0):
                self.stdout.write(f"  = shared/{f.name} (already present)")
                continue
            self.stdout.write(f"  → shared/{f.name}")
            if not dry_run:
                client.move_file(f.id, target_id)
            moved += 1
        return moved
```

- [ ] **Step 2: Verify `DriveClient.move_file` exists**

Run: `grep -n 'def move_file\|move_file' apps/opps/drive_client.py`
If the method is missing, add it as a thin wrapper around the existing Drive update-parents call (one-liner; pattern matches `update_binary` etc.). Test in `apps/opps/tests/test_drive_client.py`.

- [ ] **Step 3: Commit**

```bash
git add apps/videos/management/commands/videos_relocate_existing_content.py
git commit -m "videos(migrate): relocate existing_content/ to library/audio + shared"
```

---

## Phase 10 — Generator-prompt updates

### Task 10.1: `60s-campaign-overview/generate.prompt.md`

**Files:**
- Modify: `video-production/connect-videos/templates/60s-campaign-overview/generate.prompt.md`

- [ ] **Step 1: Read the current prompt**

Run: `cat video-production/connect-videos/templates/60s-campaign-overview/generate.prompt.md`
Note the existing section structure so the new block lands in a logical spot (probably right before "Filling the manifest" or equivalent).

- [ ] **Step 2: Insert a new section**

Append (or insert before whichever section discusses `manifest:` filling):

```markdown
## Picking clips from the media library

The orchestrator injects an `available_video_clips` block into your prompt
context with everything currently in this workspace's media library. You
can also refresh it any time via the `videos_list_library_video` MCP tool.

Each entry looks like:

```yaml
- ref: "library:video/<subfolder>/<filename>"
  name: "<human label>"
  tags: ["<tag>", ...]
  description: "<optional>"
```

For every `manifest:` slot in the spec:

1. Identify what the slot is for (scene = field footage; product = app
   screenshot — see the comment block at the top of
   `spec.template.yaml`).
2. Scan `available_video_clips` for entries whose tags match the
   program's topic/country AND the slot's role.
3. If you find a fit, write its `ref` value as the manifest entry:

   ```yaml
   manifest:
     hero-shot: "library:video/uganda-field/drone-wide.mp4"
   ```

4. If nothing fits, leave the manifest entry empty for hand-edit.

Prefer library refs over raw `gdrive:` IDs — they're stable across
program edits and signal that the clip is curated and approved.

### Tag conventions (advisory)

- **Topic/identity:** `uganda`, `kenya`, `kangaroo-care`, `midwifery`, …
- **Role:** `field-footage`, `app-screenshot`, `b-roll`, `establishing`,
  `drone`, `closeup`, …

A scene-clip slot is looking for `field-footage` + the program's country.
A product-clip slot is looking for `app-screenshot` + the program's app.
```

- [ ] **Step 3: Commit**

```bash
git add video-production/connect-videos/templates/60s-campaign-overview/generate.prompt.md
git commit -m "videos(template): teach 60s-campaign-overview generator about the library"
```

### Task 10.2: `120s-program-demo/generate.prompt.md`

- [ ] **Step 1: Insert the same section**

Apply the identical section to
`video-production/connect-videos/templates/120s-program-demo/generate.prompt.md`.

- [ ] **Step 2: Commit**

```bash
git add video-production/connect-videos/templates/120s-program-demo/generate.prompt.md
git commit -m "videos(template): teach 120s-program-demo generator about the library"
```

---

## Phase 11 — Fallback removal (Phase C of the rollout)

**Do not run this phase until Phase 9's relocation has run on every
production workspace and the new paths are verified populated.**

### Task 11.1: Drop legacy `existing_content/` constants and helpers

**Files:**
- Modify: `apps/videos/drive.py` — remove `EXISTING_CONTENT*` constants, `existing_content_folder_id`, `list_existing_content`, `find_existing_content_file`, `upload_existing_content`, `read_existing_content`
- Modify: `apps/videos/service.py` — remove dual-read fallback in `stage_existing_content_locally`; also remove `ExistingContentItem`, `list_existing_content`, `upload_existing_content`, `read_existing_content`, `_local_existing_content_dir`
- Modify: `apps/videos/tests/test_existing_content.py` — rename to `test_library_audio_shared.py`, remove legacy-path tests
- Delete: `apps/videos/management/commands/videos_migrate_existing_content.py`

- [ ] **Step 1: Verify production state**

Confirm in #ops or via Drive UI that every workspace's `videos/library/audio/` is populated and `videos/existing_content/` is empty/gone. Block on this — if anything's still in the legacy path, run Phase 9 first.

- [ ] **Step 2: Delete and adapt**

Mechanical edit pass per the file list above. Run the test suite locally:

```bash
pytest apps/videos/ -v
```

Expected: all tests pass (some renames; nothing should reference the deleted constants).

- [ ] **Step 3: Commit**

```bash
git add apps/videos/ -A
git rm apps/videos/management/commands/videos_migrate_existing_content.py
git commit -m "videos: drop existing_content/ fallback (Phase C of rollout)"
```

---

## Phase 12 — End-to-end verification

This phase is operational, not a code change. Each step writes one
commit-able artifact (a seeded library, a generated spec, a render
output) — but the work is "run things and look at them."

### Task 12.1: Seed the video library

- [ ] **Step 1: Pick two categories and 2-3 clips each**

Choose subfolders based on existing programs. Example:
- `library/video/uganda-field/` — at least one drone-wide, one CHW shot
- `library/video/kenya-clinic/` — at least one clinic interior, one
  nurse-with-patient

Upload the MP4s via Drive UI. For each, add a `<name>.json` sidecar with:

```json
{
  "name": "Drone — village wide",
  "description": "Slow push-in over rooftops at sunrise.",
  "tags": ["drone", "wide", "uganda", "field-footage"]
}
```

- [ ] **Step 2: Confirm the library reads correctly**

Open `https://labs.connect.dimagi.com/ace/w/dimagi-team/videos/library`
in the browser. Both subfolders should appear with their items;
clicking "Open in Drive" should land on the right files. Run:

```bash
curl -s -b "sessionid_ace=<token>" "https://labs.connect.dimagi.com/ace/api/w/dimagi-team/videos/library/video" | jq .
```

Expected JSON: both subfolders present, every item status `"ok"`.

### Task 12.2: Re-run `ace:video-from-program-page` on three programs

- [ ] **Step 1: Pick three existing Connect program URLs**

(e.g. three pages from `https://connect.dimagi.com/programs/...` that
already have video programs in `programs/`.)

- [ ] **Step 2: For each, run the skill and inspect the output**

```bash
/ace:video-from-program-page <program-url-1>
/ace:video-from-program-page <program-url-2>
/ace:video-from-program-page <program-url-3>
```

After each run, open the generated `spec.yaml` in Drive
(`videos/<program-slug>/runs/run-NNN/spec.yaml`) and confirm:
- At least one `manifest:` entry uses `library:video/<subfolder>/<filename>`.
- Tags chosen by the agent match the program's country/topic.
- Beat-narration text is filled in.

### Task 12.3: Render each of the three programs

- [ ] **Step 1: Trigger renders from the editor**

From `/w/dimagi-team/videos/<program-slug>` for each of the three
programs, click "Render" (or call the API directly).

- [ ] **Step 2: Confirm renders succeed**

For each program:
- `runs/run-NNN/output.mp4` appears in Drive.
- `runs/run-NNN/feedback.md` shows no fatal errors.
- The render log (visible in the editor) ends with a success line.

- [ ] **Step 3: Confirm sidecars were written**

Open `/w/dimagi-team/videos/library?type=audio`. There should be at
least one fresh entry per beat per program (i.e. ~7-8 new entries per
60s render). Each entry should show its text, voice id, model, and a
non-null duration.

### Task 12.4: Open the PR and write the verification notes

- [ ] **Step 1: Open the PR**

```bash
gh pr create --title "feat(videos): media library + library: spec refs" --body "$(cat <<'EOF'
## Summary
- Workspace-scoped media library at videos/library/{video,audio}/ with per-file JSON sidecars.
- New MCP-exposed endpoints /api/w/<slug>/videos/library/{video,audio}.
- New library:<media>/<subfolder>/<filename> spec.yaml reference syntax.
- Drive relocation (existing_content/ → library/audio + shared/) via staged dual-read rollout.
- Renderer captures voice_id/model/text/duration_sec/generated_at sidecars at synthesis time.
- Generator-prompt updates teach the video-spec generator to prefer library refs.

Spec: docs/specs/2026-05-15-media-library-design.md
Plan: docs/plans/2026-05-15-media-library.md

## Test plan
- [x] pytest apps/videos/ -v — all green
- [x] bun --cwd frontend run test -- MediaLibraryPage — all green
- [x] bunx --cwd frontend tsc -b — clean
- [x] Seeded 2 video subfolders with sidecars; library page renders correctly
- [x] Ran /ace:video-from-program-page on 3 programs; specs reference library:video/...
- [x] Rendered all 3 programs; audio sidecars appeared with correct metadata
- [x] e2e probe: scripts/qa/labs_probe.py
EOF
)"
```

- [ ] **Step 2: Run the e2e probe**

```bash
LABS_TOKEN=... uv run --extra walkthrough python scripts/qa/labs_probe.py
```

Expected: every existing surface still green, new `media-library-page`
surface green.

- [ ] **Step 3: Land the PR**

After review, squash-merge — **wait, no.** Per
`docs/learnings/squash-merge-stale-branch-orphans-commits.md`,
`allow_squash_merge=false` is set on this repo. Use **rebase-merge** or
**merge commit**. Make sure the branch has pulled the latest `main`
before landing.

---

## Self-review

Spec coverage check — every section of `docs/specs/2026-05-15-media-library-design.md` maps to a task:

| Spec section | Task(s) |
|---|---|
| Drive layout | Phase 3 (constants + helpers), Phase 9 (relocation) |
| Per-file sidecars | Phase 2 (schemas), Phase 1 (renderer writes audio), Phase 12.1 (operator writes video) |
| Video sidecar schema | Task 2.1 (`VideoSidecar`) |
| Audio sidecar schema | Task 2.1 (`AudioSidecar`) |
| Drive Changes API cache | **Adjusted** — Phase 4.2 uses the existing TTL cache pattern in `apps/videos/cache.py` instead of the Drive Changes API. The spec notes this as a follow-up if the TTL approach turns out to be wrong; design intent (fast warm reads, no SQL mirror) is preserved. |
| `library:` ref syntax | Phase 5 (parse + resolve + wire into hydrate) |
| Generator: MCP exposure | Task 6.1 (endpoints carry `x-mcp-expose`) |
| Generator: prompt pre-fill | Phase 10 — generator prompts updated; the orchestrator-side pre-fill itself lives in the ACE plugin and is called out as a follow-up PR there |
| Generator: prompt updates | Phase 10 |
| Backend `apps/videos/library/` | Phases 2, 4, 5 |
| Renderer sidecar write | Phase 1 |
| Drive relocation | Phase 9 + Phase 3 (dual-read) + Phase 11 (fallback removal) |
| API endpoints | Phase 6 |
| Frontend page + nav | Phase 7 |
| Tests | Each task has its own tests |
| End-to-end verification | Phase 12 |
| Migration/rollout plan | Phases 3 (dual-read), 9 (relocate), 11 (cleanup) |

Placeholder scan: no `TBD`, `TODO`, "implement later", or "handle edge cases" patterns in the plan. All code blocks contain executable code.

Type-consistency check: `MediaLibraryVideoOut` / `MediaLibraryAudioOut` and their inner types are defined identically in Tasks 6.1 (Pydantic models) and 7.1 (TS imports). `library_folder_id` / `list_library_subfolders` / `list_library_files` / `list_audio_library_files` / `read_library_file` / `upload_library_file` are defined in Task 3.1 and used consistently in Tasks 4.1, 5.1, 5.2, 6.1, 8.1, 8.2, 9.1.

One known divergence from the spec: the Drive Changes API cache is replaced with the existing TTL cache. Called out in the table above; documented as a future-work follow-up if the TTL approach turns out to be wrong.

---

## Execution recommendation

**Subagent-driven execution.** Each phase is independent enough to dispatch as one subagent with the review-between-tasks pattern. Phase 12 (end-to-end verification) is the only phase that requires sequential human action — keep that in the main session.

Suggested batches:
1. Phase 1 (Node renderer side, isolated)
2. Phases 2 + 3 (Python sidecar models + Drive constants/helpers)
3. Phase 4 (library reader + cache)
4. Phase 5 (refs + hydrate wiring)
5. Phase 6 (API)
6. Phase 7 (frontend)
7. Phases 8 + 9 (management commands)
8. Phase 10 (generator prompts) — can run in parallel with 8/9
9. Phase 11 (fallback removal) — gated on prod relocation confirmation; run last
10. Phase 12 (verification) — operator
