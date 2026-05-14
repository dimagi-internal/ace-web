"""Filesystem + subprocess service layer for the clip-explorer port.

The Node tsx project at ``video-production/connect-videos/`` is the
source of truth: ``programs/<slug>.yaml`` declares each video's spec,
``out/clip-explorer/<slug>/`` holds the generated HTML + media. Django
reads through to those artifacts and mutates the YAML on edit.

YAML I/O uses ruamel.yaml so we round-trip with comments and structure
preserved (matching the Node ``yaml.parseDocument`` behavior).

Renders are fire-and-forget subprocess spawns. We track a busy flag in
Redis (``videos:render:<slug>:busy``) with a TTL so a crashed render
doesn't pin the indicator forever.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import redis as _redis_sync
from django.conf import settings
from ruamel.yaml import YAML

log = logging.getLogger(__name__)


_sync_redis: _redis_sync.Redis | None = None


def _get_redis() -> _redis_sync.Redis:
    """Cached sync Redis client. Tests monkeypatch this."""
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = _redis_sync.from_url(
            settings.ACE_REDIS_URL, decode_responses=True
        )
    return _sync_redis


# ---------------------------------------------------------------------------
# Slug validation
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def is_valid_slug(slug: str) -> bool:
    """Whitelist for program slugs.

    Slugs flow into subprocess shell commands (``npm run … --program=<slug>``),
    so they must be sanitised at the boundary. Lowercase + digits + hyphens
    matches the existing ``programs/*.yaml`` filenames.
    """
    return bool(_SLUG_RE.match(slug))


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _root() -> Path:
    """Connect-videos project root (the directory `npm run` is invoked from)."""
    return Path(settings.ACE_VIDEOS_ROOT)


def _programs_dir() -> Path:
    return _root() / "programs"


def program_yaml_path(slug: str) -> Path:
    return _programs_dir() / f"{slug}.yaml"


def explorer_dir(slug: str) -> Path:
    return _root() / "out" / "clip-explorer" / slug


def feedback_path(slug: str) -> Path:
    return explorer_dir(slug) / "feedback.md"


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def _yaml() -> YAML:
    """Round-tripping YAML loader.

    ``typ='rt'`` preserves comments, anchors, and structure on
    write-back. We also widen the line so re-emitted scalars don't get
    line-wrapped weirdly.
    """
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    return y


@dataclass(frozen=True)
class ProgramRecord:
    slug: str
    workspace_slug: str | None
    raw: dict[str, Any]
    yaml_path: Path

    @property
    def name(self) -> str:
        return str(self.raw.get("name") or self.slug)

    @property
    def tagline(self) -> str | None:
        v = self.raw.get("tagline")
        return None if v is None else str(v)

    @property
    def country_focus(self) -> str | None:
        v = self.raw.get("country_focus")
        return None if v is None else str(v)

    @property
    def status(self) -> str | None:
        v = self.raw.get("status")
        return None if v is None else str(v)

    @property
    def program_url(self) -> str | None:
        v = self.raw.get("program_url")
        return None if v is None else str(v)

    @property
    def manifest_count(self) -> int:
        manifest = self.raw.get("manifest") or {}
        return len(manifest) if isinstance(manifest, dict) else 0

    @property
    def has_explorer_build(self) -> bool:
        return (explorer_dir(self.slug) / "index.html").exists()


def load_program(slug: str) -> ProgramRecord | None:
    """Load one program YAML by slug, or None if absent."""
    path = program_yaml_path(slug)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = _yaml().load(f)
    if not isinstance(data, dict):
        return None
    ws = data.get("workspace")
    return ProgramRecord(
        slug=slug,
        workspace_slug=str(ws) if ws else None,
        raw=dict(data),
        yaml_path=path,
    )


def iter_programs() -> Iterable[ProgramRecord]:
    """Yield every program YAML on disk (any workspace, no filter)."""
    pdir = _programs_dir()
    if not pdir.exists():
        return
    for path in sorted(pdir.glob("*.yaml")):
        if path.name.startswith("_"):  # _defaults.yaml etc.
            continue
        rec = load_program(path.stem)
        if rec is not None:
            yield rec


def list_programs_for_workspace(workspace_slug: str) -> list[ProgramRecord]:
    """Return programs whose ``workspace:`` field matches ``workspace_slug``."""
    return [p for p in iter_programs() if p.workspace_slug == workspace_slug]


# ---------------------------------------------------------------------------
# YAML mutation ops (mirror explore.ts::applyEdit)
# ---------------------------------------------------------------------------


def _clip_path_keys(kind: str | None, index: int) -> list[Any]:
    if kind == "scene-clip":
        return ["scene", "clips", index]
    return ["product", "beats", index]


def _get_in(doc: Any, keys: list[Any]) -> Any:
    cur = doc
    for k in keys:
        try:
            cur = cur[k]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def _set_in(doc: Any, keys: list[Any], value: Any) -> None:
    cur = doc
    for k in keys[:-1]:
        cur = cur[k]
    cur[keys[-1]] = value


@dataclass(frozen=True)
class EditResult:
    ok: bool
    message: str


def apply_edit(slug: str, body: dict[str, Any]) -> EditResult:
    """Apply one of four ops to ``programs/<slug>.yaml``.

    Mirrors ``video-production/connect-videos/scripts/explore.ts::applyEdit``
    exactly. Returns an EditResult — callers translate to ProblemError
    on failure.
    """
    path = program_yaml_path(slug)
    if not path.exists():
        return EditResult(False, f"Program {slug} not found")

    y = _yaml()
    with path.open("r", encoding="utf-8") as f:
        doc = y.load(f)

    op = body.get("op")

    if op in {"set-clip-start", "set-clip-trim", "set-clip-asset"}:
        index = body.get("index")
        kind = body.get("kind")
        if not isinstance(index, int):
            return EditResult(False, "index must be an integer")
        keys = _clip_path_keys(kind, index)
        node = _get_in(doc, keys)

        if op == "set-clip-start":
            start_seconds = body.get("start_seconds")
            if not isinstance(start_seconds, (int, float)):
                return EditResult(False, "start_seconds must be a number")
            if isinstance(node, str):
                _set_in(doc, keys, {"asset": node, "start_seconds": float(start_seconds)})
            elif isinstance(node, dict):
                node["start_seconds"] = float(start_seconds)
            else:
                return EditResult(False, f"Could not find {kind}[{index}]")
            _save_yaml(y, path, doc)
            return EditResult(True, f"Set {kind}[{index}].start_seconds = {start_seconds}")

        if op == "set-clip-trim":
            start_seconds = body.get("start_seconds")
            duration_seconds = body.get("duration_seconds")
            if not isinstance(start_seconds, (int, float)):
                return EditResult(False, "start_seconds must be a number")
            if not isinstance(duration_seconds, (int, float)):
                return EditResult(False, "duration_seconds must be a number")
            if isinstance(node, str):
                _set_in(doc, keys, {
                    "asset": node,
                    "start_seconds": float(start_seconds),
                    "duration_seconds": float(duration_seconds),
                })
            elif isinstance(node, dict):
                node["start_seconds"] = float(start_seconds)
                node["duration_seconds"] = float(duration_seconds)
            else:
                return EditResult(False, f"Could not find {kind}[{index}]")
            _save_yaml(y, path, doc)
            return EditResult(True, f"Set {kind}[{index}] trim window")

        if op == "set-clip-asset":
            alias = body.get("alias")
            if not isinstance(alias, str) or not alias:
                return EditResult(False, "alias must be a non-empty string")
            new_ref = f"@{alias}"
            if isinstance(node, str):
                if kind == "scene-clip":
                    _set_in(doc, keys, new_ref)
                else:
                    _set_in(doc, keys, {"asset": new_ref})
            elif isinstance(node, dict):
                node["asset"] = new_ref
            else:
                return EditResult(False, f"Could not find {kind}[{index}]")
            _save_yaml(y, path, doc)
            return EditResult(True, f"Swapped {kind}[{index}] -> @{alias}")

    if op == "set-narration":
        beat_id = body.get("beatId")
        text = body.get("text")
        if not isinstance(beat_id, str) or not beat_id:
            return EditResult(False, "beatId must be a non-empty string")
        if not isinstance(text, str):
            return EditResult(False, "text must be a string")
        narration = doc.setdefault("narration", {})
        by_beat = narration.setdefault("by_beat", {})
        by_beat[beat_id] = text
        _save_yaml(y, path, doc)
        return EditResult(True, f"Updated narration.by_beat.{beat_id}")

    return EditResult(False, f"Unknown op or missing args: {op!r}")


def _save_yaml(y: YAML, path: Path, doc: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        y.dump(doc, f)


# ---------------------------------------------------------------------------
# Render trigger (fire-and-forget npm chain)
# ---------------------------------------------------------------------------


_RENDER_BUSY_TTL_SECONDS = 60 * 60  # render shouldn't exceed an hour; clear stale flags


def _busy_key(slug: str) -> str:
    return f"videos:render:{slug}:busy"


def _started_key(slug: str) -> str:
    return f"videos:render:{slug}:started_at"


def trigger_rerender(slug: str, *, needs_hydrate: bool) -> bool:
    """Spawn the appropriate npm chain in the background.

    Returns True if a render was kicked off; False if one was already
    busy (skip-duplicate).
    """
    if not is_valid_slug(slug):
        raise ValueError(f"Invalid program slug: {slug!r}")
    r = _get_redis()
    # SETNX-like: only mark busy if not already busy.
    acquired = r.set(_busy_key(slug), "1", nx=True, ex=_RENDER_BUSY_TTL_SECONDS)
    if not acquired:
        log.info("videos.trigger_rerender: skipping; render already busy for %s", slug)
        return False
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    r.set(_started_key(slug), now, ex=_RENDER_BUSY_TTL_SECONDS)

    cmd_parts = []
    if needs_hydrate:
        cmd_parts.append(f"npm run hydrate -- --program={slug}")
    cmd_parts.append(f"npm run render -- --program={slug} --draft")
    cmd_parts.append(f"npm run build-clip-explorer -- --program={slug}")
    # We rely on the busy-flag TTL to clear itself; a stale flag for an
    # hour is fine (it's UX hint, not correctness).
    chain = " && ".join(cmd_parts)
    log.info("videos.trigger_rerender: spawning chain for %s (needs_hydrate=%s)", slug, needs_hydrate)
    try:
        subprocess.Popen(  # noqa: S602 — intentional shell wrapper; slug is validated upstream
            ["sh", "-c", chain],
            cwd=str(_root()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # detach from Django
        )
    except FileNotFoundError:
        # Node toolchain isn't installed in this environment — clear flag and report.
        r.delete(_busy_key(slug), _started_key(slug))
        log.warning("videos.trigger_rerender: 'sh' not found, render not started for %s", slug)
        return False
    return True


def render_status(slug: str) -> dict[str, Any]:
    r = _get_redis()
    busy = bool(r.get(_busy_key(slug)))
    started = r.get(_started_key(slug))
    if isinstance(started, bytes):
        started = started.decode("utf-8")
    return {"program_slug": slug, "busy": busy, "started_at": started}


# ---------------------------------------------------------------------------
# Library parsing (mirror buildLibraryJson from explore.ts)
# ---------------------------------------------------------------------------


# Card-block matcher mirrors explore.ts::buildLibraryJson. The trailing
# lookahead accepts ``\Z`` so the final card in a document (no following
# sibling card and no trailing wrapper ``</div>``) still matches —
# this makes the parser robust against minor template trims.
_CARD_BLOCK_RE = re.compile(
    r'<div class="lib-card">([\s\S]*?)</div>\s*</div>(?=\s*(?:<div class="lib-card"|</div>|\Z))'
)
_ALIAS_RE = re.compile(r"<h3>@([^<]+)</h3>")
_SRC_RE = re.compile(r'<video src="([^"]+)"')
_META_RE = re.compile(r"<span>([\d.]+)s · ([\dx]+)</span>")
# ``[^<]+`` already stops at the next ``<``; the trailing ``<`` literal
# would force a follow-on character that may not exist when the captured
# card block is truncated (lazy match) right after the alias text.
_USED_IN_RE = re.compile(r"lib-tag used-in[^>]*>([^<]+)")


def parse_library_html(html: str) -> list[dict[str, Any]]:
    """Parse the generated library.html into structured entries."""
    entries: list[dict[str, Any]] = []
    for m in _CARD_BLOCK_RE.finditer(html):
        block = m.group(1)
        alias_m = _ALIAS_RE.search(block)
        if not alias_m:
            continue
        alias = alias_m.group(1).strip()
        src_m = _SRC_RE.search(block)
        source_path = src_m.group(1) if src_m else None
        meta_m = _META_RE.search(block)
        dur = float(meta_m.group(1)) if meta_m else None
        res = meta_m.group(2) if meta_m else None
        used_in = [u.strip() for u in _USED_IN_RE.findall(block)]
        entries.append({
            "alias": alias,
            "source_path": source_path,
            "duration_seconds": dur,
            "resolution": res,
            "used_in": used_in,
        })
    return entries


def load_library_entries(slug: str) -> list[dict[str, Any]]:
    lib = explorer_dir(slug) / "library.html"
    if not lib.exists():
        return []
    return parse_library_html(lib.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Explorer HTML rewriting (root-absolute paths → workspace-prefixed)
# ---------------------------------------------------------------------------


def rewrite_explorer_html(html: str, *, prefix: str, csrf_cookie_name: str) -> str:
    """Rewrite the generated HTML so it can be iframed under a Django URL prefix.

    The Node-served version assumes it owns ``/`` — its fetches go to
    ``/edit``, ``/feedback``, ``/library.json``, etc. We rewrite those
    to be relative to the served page, so they resolve under the
    workspace-scoped API URL.

    We also inject a small fetch wrapper that adds the CSRF token from
    the cookie (Ninja's session auth enforces CSRF on unsafe methods).

    Args:
        html: source HTML from out/clip-explorer/<slug>/{index,library}.html
        prefix: not currently used — kept so callers can later switch to
            absolute-with-prefix rewrites if iframe sandboxing forces it.
        csrf_cookie_name: matches Django's CSRF_COOKIE_NAME for the tenant.
    """
    _ = prefix  # currently unused; kept for symmetry

    # Convert path-absolute references to page-relative ones. The page is
    # served as ``.../explorer.html`` so e.g. ``library.json`` resolves to
    # ``.../library.json`` under the same Django prefix.
    rewrites = (
        ("fetch('/feedback'", "fetch('feedback'"),
        ("fetch(\"/feedback\"", "fetch(\"feedback\""),
        ("fetch('/edit'", "fetch('edit'"),
        ("fetch(\"/edit\"", "fetch(\"edit\""),
        ("fetch('/library.json'", "fetch('library.json'"),
        ("fetch(\"/library.json\"", "fetch(\"library.json\""),
        ('href="/library.html"', 'href="library.html"'),
        ("href='/library.html'", "href='library.html'"),
        ('href="/"', 'href="explorer.html"'),
        ("href='/'", "href='explorer.html'"),
    )
    for old, new in rewrites:
        html = html.replace(old, new)

    # Inject a fetch wrapper that forwards the CSRF token from cookie.
    wrapper = (
        "<script>(function(){"
        "var _f=window.fetch;"
        "window.fetch=function(input,init){"
        "init=init||{};"
        "init.credentials=init.credentials||'include';"
        "var h=init.headers||{};"
        "var m=document.cookie.match(/(?:^|;\\s*)" + csrf_cookie_name + "=([^;]+)/);"
        "if(m){"
        "if(h instanceof Headers){h.set('X-CSRFToken',m[1]);}"
        "else{h['X-CSRFToken']=m[1];}"
        "}"
        "init.headers=h;"
        "return _f.call(this,input,init);"
        "};"
        "})();</script>"
    )
    return html.replace("<head>", "<head>" + wrapper, 1)
