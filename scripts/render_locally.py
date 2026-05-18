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

Usage::

    python scripts/render_locally.py <program-slug>
    python scripts/render_locally.py <program-slug> <run-id>
    python scripts/render_locally.py <full-editor-URL>
    python scripts/render_locally.py --publish <program-slug>

When ``--publish`` is set the script invokes
``manage.py videos_publish_artifacts`` after a successful render so the
fresh ``output.mp4`` + ``explorer.tar.gz`` land in Drive. Off by
default — the local file is enough for iteration; only publish when
you want labs to see it.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKSPACE = "dimagi-team"


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


def host_npm(slug: str, run_id: str) -> None:
    """Run the hydrate + render + build-clip-explorer chain on the host.

    Uses the host's Node / Chromium / esbuild (which match the macOS
    arch). Stdout/stderr streams directly so the user sees progress.
    ``--draft`` keeps render at preview quality (faster, smaller).
    """
    videos = REPO / "video-production" / "connect-videos"
    for step in (
        ["npm", "run", "hydrate", "--", f"--program={slug}"],
        ["npm", "run", "render", "--", f"--program={slug}", f"--run={run_id}", "--draft"],
        ["npm", "run", "build-clip-explorer", "--", f"--program={slug}", f"--run={run_id}"],
    ):
        print(f"\n==> {' '.join(step)}")
        subprocess.run(step, cwd=videos, check=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("target", help="program slug, slug/run-id, or full /videos/... URL")
    p.add_argument("run_id", nargs="?", default=None)
    p.add_argument("--workspace", default=WORKSPACE)
    p.add_argument("--publish", action="store_true",
                   help="After render, push output.mp4 + explorer.tar.gz to Drive.")
    args = p.parse_args()

    if args.run_id:
        slug, run_id = args.target, args.run_id
    else:
        slug, run_id = parse_target(args.target)

    print(f"==> workspace={args.workspace} program={slug} run={run_id} publish={args.publish}")

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
    host_npm(slug, run_id)

    if args.publish:
        print("\n==> [3/3] Publish artifacts to Drive (container)")
        subprocess.run([
            "docker", "compose", "exec", "-T", "app",
            "python", "manage.py", "videos_publish_artifacts",
            f"--workspace={args.workspace}", f"--program={slug}", f"--run={run_id}",
        ], cwd=REPO, check=True)
    else:
        print("\n==> [3/3] Skipping publish (pass --publish to push to Drive)")

    out = (
        REPO / "video-production" / "connect-videos"
        / "programs" / slug / "runs" / run_id / "output.mp4"
    )
    print(f"\n==> Done. Output: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
