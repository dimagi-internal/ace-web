#!/usr/bin/env python3
"""Render a video run on bare Mac metal, end-to-end.

When ace-web's UI "Re-render" button shells out via ``subprocess.Popen``
in ``apps.videos.service.trigger_rerender``, the command runs *inside*
the Django container. On macOS that path is broken: the bind-mount of
``video-production/`` overlays the host's macOS ``node_modules`` into
the Linux container, so the first esbuild call dies on a
``darwin-arm64`` binary in a Linux runtime. See
``programs/<slug>/runs/<run>/render.log`` after a UI re-render — it'll
end with ``generateBinPath ENOENT``.

This script is the "click Re-render" equivalent for local dev: it does
the same chain as ``trigger_rerender`` but uses the host's Node /
Chromium / esbuild — which actually run — for the npm steps, and
hands off staging + publishing to the Django container (which has the
Drive SA credentials).

Why not just fix the docker mount? Two reasons:

- Renders on bare-metal macOS are 1-3 min; the same renders inside
  Docker Desktop's Linux VM are noticeably slower due to the
  VirtioFS / GPU-less Chromium overhead.
- The user explicitly wanted Mac-metal renders for iteration speed.

A proper architectural fix (Redis-queued host worker) would automate
this — see ``docs/specs/`` if/when that's prioritised. Until then this
script is the manual path.

Two input modes
===============

**Drive mode** (default) — the program already lives in ace-web/Drive.
Stage the spec FROM Drive via the Django container, then render::

    python scripts/render_locally.py <program-slug>
    python scripts/render_locally.py <program-slug> <run-id>
    python scripts/render_locally.py <full-editor-URL>
    python scripts/render_locally.py --publish <program-slug>

**Local-spec mode** (``--local-spec``) — render a spec that exists only
on the local filesystem, with NO Drive and NO Django container. The
caller (e.g. canopy's DDD `connect-ddd-walkthrough` emitter) has already
produced a ``spec.yaml`` + a master clip; this stages them straight into
``connect-videos/programs/<slug>/runs/<run>/`` and runs the host npm
render. This is the path for rendering any DDD narrative locally::

    python scripts/render_locally.py --local-spec /path/to/spec.yaml \
        --master /path/to/walkthrough.mp4

    # final (1080p) instead of the default --draft preview:
    python scripts/render_locally.py --local-spec spec.yaml --master clip.mp4 --final

The slug + run come from the spec (``slug:`` / ``--run``); the master is
copied to whatever path the spec's ``manifest.master: file:…`` ref names.
``--publish`` is rejected in local-spec mode (there is no Drive program
to publish to).

When ``--publish`` is set (Drive mode only) the script invokes
``manage.py videos_publish_artifacts`` after a successful render so the
fresh ``output.mp4`` + ``explorer.tar.gz`` land in Drive. Off by
default — the local file is enough for iteration; only publish when
you want labs to see it.

The connect-videos project rendered into defaults to this repo's
vendored copy (``video-production/connect-videos``); override with
``$CONNECT_VIDEOS_ROOT`` / ``--connect-videos-root`` to render against a
different checkout's installed toolchain.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKSPACE = "dimagi-team"

# Framing-beat seconds the connect-walkthrough template adds around the
# body clips, used by the timing report to separate "clip footage" from
# "VO overrun hold". Kept in sync with the emitter's intro/outro defaults.
_INTRO_SECONDS = 4
_OUTRO_SECONDS = 5


def connect_videos_root() -> Path:
    """The connect-videos project to render into.

    Defaults to this repo's vendored ``video-production/connect-videos``.
    ``$CONNECT_VIDEOS_ROOT`` overrides it so a caller can target a
    canonical install regardless of which checkout this script lives in.
    """
    env = os.environ.get("CONNECT_VIDEOS_ROOT")
    return Path(env).expanduser().resolve() if env else REPO / "video-production" / "connect-videos"


def load_dotenv_into_env() -> None:
    """Merge the repo's `.env` into os.environ for subprocess inheritance.

    The renderer's per-beat voiceover synthesis (ElevenLabs) reads
    `ELEVENLABS_API_KEY` from process env. Docker-compose loads `.env`
    automatically when starting containers, but plain `subprocess.run`
    out of a fresh shell doesn't — so without this, a host-side render
    silently drops voice (logs the "not set; rendering silent video"
    warning and skips synthesis). Existing env values win so a caller
    can override per-invocation. Keys with embedded newlines (Drive SA
    JSON) are skipped — they'd break naive line parsing and the host
    npm chain doesn't need them anyway.
    """
    env_path = REPO / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def parse_target(s: str) -> tuple[str, str]:
    """Accept a program slug, ``<slug>/<run-id>``, or a /videos/.../runs/... URL."""
    m = re.search(r"/videos/([^/]+)/runs/([^/?#]+)", s)
    if m:
        return m.group(1), m.group(2)
    if "/" in s:
        slug, run_id = s.split("/", 1)
        return slug, run_id
    return s, "run-001"


def run_in_container(script: str) -> None:
    """Execute a Python snippet inside the running ace-web `app` container.

    Used for steps that need Drive SA credentials + DATABASE_URL pointed
    at Postgres (both live in the container, not the host shell).
    """
    subprocess.run(
        ["docker", "compose", "exec", "-T", "app", "python", "-c", script],
        cwd=REPO, check=True,
    )


def host_npm(cv: Path, slug: str, run_id: str, *, draft: bool = True,
             hydrate: bool = True, explorer: bool = True) -> None:
    """Run the npm render chain on the host (bare-metal Mac).

    Uses the host's Node / Chromium / esbuild (which match the macOS
    arch). Stdout/stderr streams directly so the user sees progress.
    ``--draft`` keeps render at preview quality (faster, smaller).

    ``hydrate`` (pull assets from the Drive cache) and ``explorer``
    (build the clip-explorer UI) are skipped in local-spec mode: the
    assets are already local files and the explorer isn't needed to get
    the mp4.
    """
    steps: list[list[str]] = []
    if hydrate:
        steps.append(["npm", "run", "hydrate", "--", f"--program={slug}"])
    render = ["npm", "run", "render", "--", f"--program={slug}", f"--run={run_id}"]
    if draft:
        render.append("--draft")
    steps.append(render)
    if explorer:
        steps.append(
            ["npm", "run", "build-clip-explorer", "--", f"--program={slug}", f"--run={run_id}"]
        )
    for step in steps:
        print(f"\n==> {' '.join(step)}")
        subprocess.run(step, cwd=cv, check=True)


def _load_spec(spec_path: Path) -> dict:
    """Parse a connect-videos program spec. Prefers PyYAML; falls back to
    a tiny regex reader so the script stays runnable in a bare stdlib
    interpreter (only the two fields we need: top-level ``slug`` and
    ``manifest.master``)."""
    text = spec_path.read_text()
    try:
        import yaml  # type: ignore

        doc = yaml.safe_load(text)
        if isinstance(doc, dict):
            return doc
    except Exception:
        pass
    slug_m = re.search(r"^slug:\s*[\"']?([A-Za-z0-9._-]+)", text, re.M)
    master_m = re.search(r"^\s*master:\s*[\"']?(\S+?)[\"']?\s*$", text, re.M)
    return {
        "slug": slug_m.group(1) if slug_m else None,
        "manifest": {"master": master_m.group(1) if master_m else None},
    }


def _copy_into_place(src: Path, dest: Path) -> None:
    """Copy src → dest, but no-op when they're already the same file (the
    caller may pass a spec/clip that already lives in the staging tree —
    e.g. a re-render in place)."""
    if dest.exists() and src.resolve() == dest.resolve():
        return
    shutil.copyfile(src, dest)


def stage_local_spec(cv: Path, spec_path: Path, run_id: str, master_path: Path | None) -> str:
    """Stage a local spec + master clip into connect-videos (no Drive).

    Writes ``programs/<slug>/runs/<run>/spec.yaml`` and copies the master
    clip to the path the spec's ``manifest.master: file:…`` ref names.
    Returns the resolved slug.
    """
    doc = _load_spec(spec_path)
    slug = doc.get("slug")
    if not slug:
        raise SystemExit(f"Could not read `slug` from {spec_path}")

    dest_spec = cv / "programs" / slug / "runs" / run_id / "spec.yaml"
    dest_spec.parent.mkdir(parents=True, exist_ok=True)
    _copy_into_place(spec_path, dest_spec)
    print(f"==> staged spec → {dest_spec}")

    if master_path:
        master_ref = (doc.get("manifest") or {}).get("master") or ""
        if not master_ref.startswith("file:"):
            raise SystemExit(
                f"--master given but spec manifest.master is not a file: ref ({master_ref!r}).\n"
                "Local-spec mode copies the master to the file: path the spec names; "
                "emit the spec with a file: master ref (the DDD emitter does this)."
            )
        dest_master = cv / master_ref[len("file:"):]
        dest_master.parent.mkdir(parents=True, exist_ok=True)
        _copy_into_place(master_path, dest_master)
        print(f"==> staged master → {dest_master}")

    return slug


def timing_report(cv: Path, slug: str, run_id: str) -> None:
    """Print clip-footage vs actual-duration so the author can see how much
    the render held a last frame waiting for VO to finish (the overrun).

    Expected = sum of every beat's ``seconds`` in the spec (intro + body
    clip ranges + outro). Actual = the rendered mp4's real duration. The
    delta is held-frame time: trim narration to shrink it toward the
    target. Best-effort — never fatal.
    """
    try:
        import json

        run_dir = cv / "programs" / slug / "runs" / run_id
        spec_text = (run_dir / "spec.yaml").read_text()
        beat_secs = [float(s) for s in re.findall(r"^\s*seconds:\s*([0-9.]+)\s*$", spec_text, re.M)]
        expected = sum(beat_secs)
        out = run_dir / "output.mp4"
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(out)],
            capture_output=True, text=True, check=True,
        )
        actual = float(json.loads(probe.stdout)["format"]["duration"])
        overrun = actual - expected
        print("\n==> Timing report")
        print(f"    clip footage (spec beats): {expected:6.1f}s")
        print(f"    rendered duration:         {actual:6.1f}s")
        flag = "  ⚠ VO overruns clips — trim narration to play continuously" if overrun > 3 else ""
        print(f"    held-frame overrun:        {overrun:+6.1f}s{flag}")
    except Exception as e:  # noqa: BLE001 — report is advisory
        print(f"\n==> Timing report skipped ({e})")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("target", nargs="?", default=None,
                   help="Drive mode: program slug, slug/run-id, or full /videos/... URL")
    p.add_argument("run_id", nargs="?", default=None)
    p.add_argument("--workspace", default=WORKSPACE)
    p.add_argument("--publish", action="store_true",
                   help="Drive mode only: push output.mp4 + explorer.tar.gz to Drive after render.")
    p.add_argument("--local-spec", default=None,
                   help="Local-spec mode: path to a connect-videos spec.yaml to render "
                        "(no Drive, no container). Slug + run come from the spec.")
    p.add_argument("--master", default=None,
                   help="Local-spec mode: master clip copied to the spec's "
                        "manifest.master file: path.")
    p.add_argument("--run", default=None,
                   help="Local-spec mode: run id (default run-001).")
    p.add_argument("--final", action="store_true",
                   help="Render at final quality (skip the default --draft preview).")
    p.add_argument("--connect-videos-root", default=None,
                   help="Override the connect-videos project to render into "
                        "(also honored via $CONNECT_VIDEOS_ROOT).")
    args = p.parse_args()

    if args.connect_videos_root:
        os.environ["CONNECT_VIDEOS_ROOT"] = args.connect_videos_root
    cv = connect_videos_root()
    if not (cv / "package.json").is_file():
        print(f"ERROR: no connect-videos project at {cv}.\n"
              "       Point at a checkout via --connect-videos-root / $CONNECT_VIDEOS_ROOT.",
              file=sys.stderr)
        return 2

    load_dotenv_into_env()
    have_eleven = bool(os.environ.get("ELEVENLABS_API_KEY"))

    local_mode = bool(args.local_spec)
    if not local_mode and not args.target:
        p.error("provide a program slug/URL (Drive mode) or --local-spec <spec> (local mode)")
    if local_mode and args.publish:
        p.error("--publish is Drive-only; local-spec renders have no Drive program to publish to")

    if not have_eleven:
        # The renderer (post-2026-05-18) hard-fails when the spec asks
        # for elevenlabs voice and the key isn't set. We pre-check here
        # so the user sees the actionable error before npm spins up its
        # whole pipeline. If you genuinely want a silent render, edit
        # render_locally.py and pass --no-voice to npm run render, or
        # set spec.voice.provider to something non-elevenlabs.
        print(
            "\nERROR: ELEVENLABS_API_KEY not found in env or in .env.\n"
            "       The renderer will refuse to render a silent video by "
            "default (it used to silently warn — that hid real failures).\n"
            "       Drop the key into .env, then re-run.",
            file=sys.stderr,
        )
        return 2

    if local_mode:
        run_id = args.run or "run-001"
        print(f"==> local-spec mode: spec={args.local_spec} program=(from spec) run={run_id} "
              f"voice={'on' if have_eleven else 'MISSING KEY'} root={cv}")
        master = Path(args.master) if args.master else None
        slug = stage_local_spec(cv, Path(args.local_spec), run_id, master)

        print("\n==> Run npm render on host (bare-metal Mac)")
        host_npm(cv, slug, run_id, draft=not args.final, hydrate=False, explorer=False)
    else:
        if args.run_id:
            slug, run_id = args.target, args.run_id
        else:
            slug, run_id = parse_target(args.target)
        print(f"==> workspace={args.workspace} program={slug} run={run_id} "
              f"publish={args.publish} voice={'on' if have_eleven else 'MISSING KEY'} root={cv}")

        print("\n==> [1/3] Stage spec + shared content from Drive (container)")
        run_in_container(f"""
import django; django.setup()
from apps.workspaces.models import Workspace
from apps.videos.service import (
    _stage_spec, stage_existing_content_locally, prefetch_manifest_to_cache,
)
ws = Workspace.objects.get(slug={args.workspace!r})
_stage_spec(ws, {slug!r}, {run_id!r})
stage_existing_content_locally(ws)
print('prefetch:', prefetch_manifest_to_cache(ws, {slug!r}, {run_id!r}))
""")

        print("\n==> [2/3] Run npm chain on host (bare-metal Mac)")
        host_npm(cv, slug, run_id, draft=not args.final)

    print("\n==> Level-1 QA probe")
    # Run the smoke probe in-process so its output streams to the same
    # terminal. Don't `check=True` — a WARN (exit 1) should print but
    # not abort the render; a FAIL (exit 2) prints a clear "FAILED"
    # banner at the end so the user notices. It honors CONNECT_VIDEOS_ROOT
    # (inherited via os.environ) so it probes the same project we rendered.
    qa_rc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "qa_render.py"), slug, run_id],
        cwd=REPO,
    ).returncode

    timing_report(cv, slug, run_id)

    if not local_mode and args.publish:
        print("\n==> Publish artifacts to Drive (container)")
        subprocess.run([
            "docker", "compose", "exec", "-T", "app",
            "python", "manage.py", "videos_publish_artifacts",
            f"--workspace={args.workspace}", f"--program={slug}", f"--run={run_id}",
        ], cwd=REPO, check=True)
    elif not local_mode:
        print("\n==> Skipping publish (pass --publish to push to Drive)")

    out = cv / "programs" / slug / "runs" / run_id / "output.mp4"
    print(f"\n==> Done. Output: {out}")
    if qa_rc == 2:
        print("==> ⚠ QA probe reported FAIL — see checks above before shipping.")
    elif qa_rc == 1:
        print("==> ⚠ QA probe reported WARN — worth eyeballing the noted beats.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
