#!/usr/bin/env python3
"""Level-1 smoke probe for a rendered Connect video.

Runs after `render_locally.py` (or manually). Catches the regressions
we've shipped silently this week without anyone noticing until opening
the player:

- Render exits "ok" but the audio track is empty (the swallowed
  ELEVENLABS_API_KEY case — fixed via loud-fail upstream, but worth
  detecting from the file too in case some future renderer path makes
  the same mistake).
- Headline stat overflows the 1920px canvas because someone used a
  larger value than the font formula expected.
- A test sentinel like ``E2E-20260515T185648Z-…`` leaks into the
  rendered spec and lands in the player as live content.
- The output mp4 is broken — wrong duration, no video stream, etc.

The checks are deliberately deterministic (ffprobe + ffmpeg frame
extraction + Python pixel-variance math + string grep of the spec).
No vision model, no LLM. That's Level 2 — see the GitHub issue.

Usage::

    python scripts/qa_render.py <program-slug>
    python scripts/qa_render.py <program-slug> <run-id>
    python scripts/qa_render.py <full-editor-URL>

Exit codes:

- 0 — all checks pass
- 1 — at least one WARN (worth eyeballing, not blocking)
- 2 — at least one FAIL (almost certainly broken)

Side effect: each beat's midpoint frame is saved to
``<run-dir>/qa-frames/<beat-id>.png`` so you can open the folder and
flip through them. The frames are git-ignored (under the
explorer/programs path that the spec edits already drift on).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


def connect_videos_root() -> Path:
    """The connect-videos project to probe. Mirrors render_locally.py:
    defaults to this repo's vendored copy; ``$CONNECT_VIDEOS_ROOT``
    overrides it so the probe targets the same project that was rendered."""
    env = os.environ.get("CONNECT_VIDEOS_ROOT")
    return Path(env).expanduser().resolve() if env else REPO / "video-production" / "connect-videos"


def _rel(path: Path) -> str:
    """Display a path relative to REPO when it's underneath it, else as-is —
    a CONNECT_VIDEOS_ROOT override can put the run dir outside this repo."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)

# Lifted from programs/global_style.yaml so the probe doesn't have to spin
# up Django to read the spec. If a program's spec.yaml overrides
# `beats` (rare — it's a global-template structure) the override would
# shift these — we accept that drift for now since the probe's purpose
# is catching template-level regressions, not per-spec mismatches.
DEFAULT_BEAT_SCHEDULE: list[tuple[str, float]] = [
    ("hook", 4),
    ("cycle", 8),
    ("handoff", 3),
    ("scene", 7),
    ("problem", 10),
    ("product", 12),
    ("impact", 8),
    ("cta", 8),
]
EXPECTED_TOTAL_SECONDS = sum(d for _, d in DEFAULT_BEAT_SCHEDULE)  # 60

# Test-sentinel patterns that should never leak into rendered content.
# Bug class: spec.yaml retains placeholder strings from an automated
# fixture, and the renderer dutifully prints them as captions or stat
# numbers.
# Example value caught: "E2E-20260515T185648Z-narration line for the beat editor smoke test."
SENTINEL_PATTERNS: list[str] = [
    r"\bE2E-\w+",
    r"\bsmoke[\s-]?test\b",
    r"\bplaceholder\b",
    r"\bTODO\b",
    r"\bFIXME\b",
    r"\blorem ipsum\b",
]


def parse_target(s: str) -> tuple[str, str]:
    m = re.search(r"/videos/([^/]+)/runs/([^/?#]+)", s)
    if m:
        return m.group(1), m.group(2)
    if "/" in s:
        slug, run_id = s.split("/", 1)
        return slug, run_id
    return s, "run-001"


# ---------------------------------------------------------------------------
# Check helpers — each returns (status, message). Status is one of
# "ok" | "warn" | "fail". The runner aggregates them.
# ---------------------------------------------------------------------------


def check_output_exists(mp4: Path) -> tuple[str, str]:
    if not mp4.is_file():
        return "fail", f"{mp4} does not exist"
    size = mp4.stat().st_size
    if size < 100_000:
        return "fail", f"output.mp4 is suspiciously small ({size} bytes)"
    return "ok", f"output.mp4 exists ({size:,} bytes)"


def probe_streams(mp4: Path) -> dict:
    """Run ffprobe + return parsed format/streams JSON."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(mp4),
        ],
        check=True, capture_output=True, text=True,
    )
    return json.loads(out.stdout)


def check_duration(meta: dict) -> tuple[str, str]:
    try:
        dur = float(meta["format"]["duration"])
    except (KeyError, ValueError):
        return "fail", "no duration in ffprobe output"
    # Renderer rounds, audio realignment can pull slightly long. ±2s is
    # plenty of slack for the 60s template.
    if abs(dur - EXPECTED_TOTAL_SECONDS) > 2:
        return "warn", f"duration {dur:.2f}s drifted from expected {EXPECTED_TOTAL_SECONDS}s"
    return "ok", f"duration {dur:.2f}s (expected ~{EXPECTED_TOTAL_SECONDS}s)"


def check_audio_stream(meta: dict) -> tuple[str, str]:
    audio = [s for s in meta.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio:
        return "fail", "no audio stream — render is silent"
    a = audio[0]
    # An "all silence" track still has a stream, just very low bitrate.
    # In practice voiceover lands at 60–100kbps mono; music-bed-only
    # silent voice came out near 128kbps stereo (because of the music
    # bed). Threshold of 30kbps with a channel check distinguishes the
    # two cases — real voice is mono ~70kbps; silent-with-music-bed is
    # stereo 128kbps with no narration content.
    try:
        bitrate = int(a.get("bit_rate", "0"))
    except ValueError:
        bitrate = 0
    channels = a.get("channels")
    if bitrate < 30_000:
        return "fail", f"audio bitrate {bitrate} suspiciously low — likely silent"
    if channels != 1:
        return "warn", (
            f"audio is {channels}ch (expected mono voiceover); "
            "could be silent-with-music-bed if the renderer dropped voice"
        )
    return "ok", f"audio: mono @ {bitrate:,}bps"


def check_video_stream(meta: dict) -> tuple[str, str]:
    video = [s for s in meta.get("streams", []) if s.get("codec_type") == "video"]
    if not video:
        return "fail", "no video stream"
    v = video[0]
    return "ok", f"video: {v.get('codec_name')} {v.get('width')}x{v.get('height')}"


def check_sentinels(spec_yaml: str) -> tuple[str, str]:
    hits: list[tuple[str, str]] = []
    for pat in SENTINEL_PATTERNS:
        for m in re.finditer(pat, spec_yaml, re.IGNORECASE):
            hits.append((pat, m.group(0)))
    if not hits:
        return "ok", "no sentinel placeholder strings in spec"
    sample = ", ".join(f"{h[1]!r}" for h in hits[:3])
    return "fail", f"found {len(hits)} sentinel string(s) — fix in spec.yaml: {sample}"


def extract_frame(mp4: Path, at_seconds: float, dest: Path) -> bool:
    """Extract a single frame at `at_seconds`. Returns True on success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y", "-ss", str(at_seconds),
            "-i", str(mp4), "-frames:v", "1", str(dest),
        ],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and dest.is_file()


def frame_is_solid(png: Path) -> bool:
    """Detect 'all one color' frames (all black, all white, etc.).

    Such frames are usually a render bug — a Sequence boundary
    off-by-one, an asset that failed to load and left a black hole, a
    composition that rendered nothing while the audio kept playing.
    The check: sample every 16th pixel of the luminance plane; if max
    minus min < 8 (out of 256) the frame is effectively flat.
    """
    try:
        from PIL import Image
    except ImportError:
        # Pillow ships with our dev extras; if it's missing we
        # gracefully no-op instead of failing the whole probe.
        return False
    try:
        img = Image.open(png).convert("L")
        px = list(img.getdata())[::16]
        if not px:
            return True
        mn, mx = min(px), max(px)
        return (mx - mn) < 8
    except Exception:
        return False


def check_beat_frames(mp4: Path, run_dir: Path) -> list[tuple[str, str]]:
    """Extract a frame at the midpoint of each scheduled beat and check
    for solid-color (likely-broken) frames. Returns one (status, msg)
    tuple per beat."""
    out_dir = run_dir / "qa-frames"
    results: list[tuple[str, str]] = []
    t_cursor = 0.0
    for beat_id, dur in DEFAULT_BEAT_SCHEDULE:
        mid = t_cursor + dur / 2
        png = out_dir / f"{beat_id}.png"
        ok = extract_frame(mp4, mid, png)
        if not ok:
            results.append(
                ("warn", f"beat {beat_id}: ffmpeg failed to extract frame at {mid:.1f}s")
            )
        elif frame_is_solid(png):
            results.append((
                "warn",
                f"beat {beat_id} @ {mid:.1f}s: frame looks solid (all-black or all-white?)",
            ))
        else:
            results.append(
                ("ok", f"beat {beat_id} @ {mid:.1f}s: rendered (saved to {_rel(png)})")
            )
        t_cursor += dur
    return results


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


STATUS_ICON = {"ok": "✓", "warn": "⚠", "fail": "✗"}
STATUS_RANK = {"ok": 0, "warn": 1, "fail": 2}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("target", help="program slug, slug/run-id, or full /videos/... URL")
    p.add_argument("run_id", nargs="?", default=None)
    args = p.parse_args()

    if args.run_id:
        slug, run_id = args.target, args.run_id
    else:
        slug, run_id = parse_target(args.target)

    run_dir = connect_videos_root() / "programs" / slug / "runs" / run_id
    mp4 = run_dir / "output.mp4"
    spec_path = run_dir / "spec.yaml"

    print(f"==> QA: program={slug} run={run_id}\n")

    results: list[tuple[str, str]] = []

    # Output sanity
    results.append(check_output_exists(mp4))
    if results[-1][0] == "fail":
        # Without an mp4 the rest of the checks are pointless.
        _print_summary(results)
        return _exit_code(results)

    # ffprobe-based stream checks
    meta = probe_streams(mp4)
    results.append(check_video_stream(meta))
    results.append(check_audio_stream(meta))
    results.append(check_duration(meta))

    # Spec-level sentinel detection
    if spec_path.is_file():
        results.append(check_sentinels(spec_path.read_text()))
        # Also validate the spec parses as YAML (cheap sanity).
        try:
            yaml.safe_load(spec_path.read_text())
            results.append(("ok", "spec.yaml parses as valid YAML"))
        except yaml.YAMLError as e:
            results.append(("fail", f"spec.yaml is malformed: {e}"))
    else:
        results.append(("warn", f"no spec.yaml at {spec_path} — can't check sentinels"))

    # Per-beat midpoint frame checks
    results.extend(check_beat_frames(mp4, run_dir))

    _print_summary(results)
    return _exit_code(results)


def _print_summary(results: list[tuple[str, str]]) -> None:
    counts = {"ok": 0, "warn": 0, "fail": 0}
    for status, msg in results:
        counts[status] += 1
        print(f"  {STATUS_ICON[status]} [{status.upper():4s}] {msg}")
    print()
    print(f"==> {counts['ok']} ok · {counts['warn']} warn · {counts['fail']} fail")


def _exit_code(results: list[tuple[str, str]]) -> int:
    worst = max((STATUS_RANK[s] for s, _ in results), default=0)
    return worst  # 0 ok, 1 warn, 2 fail


if __name__ == "__main__":
    sys.exit(main())
