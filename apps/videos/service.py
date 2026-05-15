"""Filesystem + subprocess service layer for the videos surface.

Storage layout (mirrors opps/runs in ace-web):

    programs/<slug>/runs/run-001/spec.yaml       ← video spec
    programs/<slug>/runs/run-001/output.mp4      ← muxed render
    programs/<slug>/runs/run-001/explorer/       ← built explorer (index.html + media/)

Each iteration is a folder snapshot. Editing a run mutates that run's
spec.yaml; forking copies spec.yaml into the next ``run-NNN`` directory
and starts fresh from there.

YAML I/O uses ruamel.yaml so we round-trip with comments and structure
preserved. Renders are fire-and-forget subprocess spawns; a Redis busy
flag scoped to (slug, run_id) tracks in-flight work with a TTL.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import shutil
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
# Slug / run-id validation
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_RUN_RE = re.compile(r"^run-(\d{3,})$")


def is_valid_slug(slug: str) -> bool:
    """Whitelist for program slugs. Lowercase + digits + hyphens."""
    return bool(_SLUG_RE.match(slug))


def is_valid_run_id(run_id: str) -> bool:
    """Whitelist for run ids (e.g. ``run-001``)."""
    return bool(_RUN_RE.match(run_id))


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _root() -> Path:
    """Connect-videos project root (the directory `npm run` is invoked from)."""
    return Path(settings.ACE_VIDEOS_ROOT)


def _programs_dir() -> Path:
    return _root() / "programs"


def program_dir(slug: str) -> Path:
    return _programs_dir() / slug


def runs_dir(slug: str) -> Path:
    return program_dir(slug) / "runs"


def run_dir(slug: str, run_id: str) -> Path:
    return runs_dir(slug) / run_id


def spec_path(slug: str, run_id: str) -> Path:
    return run_dir(slug, run_id) / "spec.yaml"


def output_path(slug: str, run_id: str) -> Path:
    return run_dir(slug, run_id) / "output.mp4"


def explorer_dir(slug: str, run_id: str) -> Path:
    return run_dir(slug, run_id) / "explorer"


def feedback_path(slug: str, run_id: str) -> Path:
    return explorer_dir(slug, run_id) / "feedback.md"


# ---------------------------------------------------------------------------
# Runs discovery
# ---------------------------------------------------------------------------


def list_run_ids(slug: str) -> list[str]:
    """Return all run ids for ``slug`` sorted ascending."""
    rdir = runs_dir(slug)
    if not rdir.exists():
        return []
    return sorted(
        p.name for p in rdir.iterdir()
        if p.is_dir() and _RUN_RE.match(p.name)
    )


def latest_run_id(slug: str) -> str | None:
    ids = list_run_ids(slug)
    return ids[-1] if ids else None


def next_run_id(slug: str) -> str:
    ids = list_run_ids(slug)
    if not ids:
        return "run-001"
    last = ids[-1]
    n = int(last.removeprefix("run-"))
    return f"run-{n + 1:03d}"


def create_program_from_spec(slug: str, spec_yaml: str) -> Path:
    """Create programs/<slug>/runs/run-001/spec.yaml with the supplied
    YAML body. Validates: slug shape, slug doesn't collide, body parses
    as a YAML mapping, and the `slug:` field inside the body matches
    the path slug (catches the most common copy-paste mistake).

    Returns the absolute path that was written.

    Raises ``ValueError`` on validation failure and
    ``FileExistsError`` when the program directory already exists —
    the caller (API) translates these into RFC 7807 problem responses.
    """
    if not is_valid_slug(slug):
        raise ValueError(f"Invalid program slug: {slug!r}")
    pdir = program_dir(slug)
    if pdir.exists():
        raise FileExistsError(f"Program already exists: {pdir}")

    # Parse the supplied YAML so we can sanity-check it before writing.
    try:
        doc = _yaml().load(spec_yaml)
    except Exception as e:  # ruamel.yaml's own error types vary
        raise ValueError(f"spec_yaml is not valid YAML: {e}") from e
    if not isinstance(doc, dict):
        raise ValueError("spec_yaml must parse to a YAML mapping at the top level")
    yaml_slug = doc.get("slug")
    if yaml_slug != slug:
        raise ValueError(
            f"spec_yaml.slug ({yaml_slug!r}) must match the URL slug ({slug!r})"
        )
    if not doc.get("workspace"):
        raise ValueError("spec_yaml.workspace is required")

    run_001 = run_dir(slug, "run-001")
    run_001.mkdir(parents=True, exist_ok=True)
    target = run_001 / "spec.yaml"
    target.write_text(spec_yaml, encoding="utf-8")
    return target


def copy_run(slug: str, from_run_id: str) -> str:
    """Snapshot ``spec.yaml`` from ``from_run_id`` into a fresh
    ``run-NNN`` and return the new run id. Both runs stay mutable
    — this is "save-as", not "fork". Use it when you want to keep
    the current run around as a known-good baseline before trying
    something different in a new run.

    Output + explorer start empty — re-render to populate them.
    """
    src = spec_path(slug, from_run_id)
    if not src.exists():
        raise FileNotFoundError(f"Source spec not found: {src}")
    new_id = next_run_id(slug)
    new_dir = run_dir(slug, new_id)
    new_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, new_dir / "spec.yaml")
    return new_id


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def _yaml() -> YAML:
    """Round-tripping YAML loader: preserves comments + structure."""
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    return y


@dataclass(frozen=True)
class ProgramRecord:
    slug: str
    run_id: str
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
        return (explorer_dir(self.slug, self.run_id) / "index.html").exists()

    @property
    def has_output(self) -> bool:
        return output_path(self.slug, self.run_id).exists()


def load_program_run(slug: str, run_id: str) -> ProgramRecord | None:
    """Load the spec.yaml for one specific run, or None if absent."""
    if not is_valid_slug(slug) or not is_valid_run_id(run_id):
        return None
    path = spec_path(slug, run_id)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = _yaml().load(f)
    if not isinstance(data, dict):
        return None
    ws = data.get("workspace")
    return ProgramRecord(
        slug=slug,
        run_id=run_id,
        workspace_slug=str(ws) if ws else None,
        raw=dict(data),
        yaml_path=path,
    )


def load_program(slug: str, run_id: str | None = None) -> ProgramRecord | None:
    """Load a program — defaults to its latest run when run_id is None."""
    if not is_valid_slug(slug):
        return None
    rid = run_id or latest_run_id(slug)
    if rid is None:
        return None
    return load_program_run(slug, rid)


def iter_programs() -> Iterable[ProgramRecord]:
    """Yield the latest run of every program directory on disk."""
    pdir = _programs_dir()
    if not pdir.exists():
        return
    for entry in sorted(pdir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        rid = latest_run_id(entry.name)
        if rid is None:
            continue
        rec = load_program_run(entry.name, rid)
        if rec is not None:
            yield rec


def list_programs_for_workspace(workspace_slug: str) -> list[ProgramRecord]:
    """Return latest-run records visible to a workspace."""
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


def apply_edit(slug: str, run_id: str, body: dict[str, Any]) -> EditResult:
    """Apply one of four ops to ``programs/<slug>/runs/<run_id>/spec.yaml``.

    Mirrors ``video-production/connect-videos/scripts/explore.ts::applyEdit``.
    """
    path = spec_path(slug, run_id)
    if not path.exists():
        return EditResult(False, f"Spec not found for {slug}/{run_id}")

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


_RENDER_BUSY_TTL_SECONDS = 60 * 60  # render shouldn't exceed an hour


def _busy_key(slug: str, run_id: str) -> str:
    return f"videos:render:{slug}:{run_id}:busy"


def _started_key(slug: str, run_id: str) -> str:
    return f"videos:render:{slug}:{run_id}:started_at"


def trigger_build_only(slug: str, run_id: str) -> bool:
    """Spawn just `build-clip-explorer` (no render). Sub-second."""
    if not is_valid_slug(slug) or not is_valid_run_id(run_id):
        raise ValueError(f"Invalid slug or run_id: {slug!r} / {run_id!r}")
    r = _get_redis()
    acquired = r.set(_busy_key(slug, run_id), "1", nx=True, ex=_RENDER_BUSY_TTL_SECONDS)
    if not acquired:
        return False
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    r.set(_started_key(slug, run_id), now, ex=_RENDER_BUSY_TTL_SECONDS)
    chain = f"npm run build-clip-explorer -- --program={slug} --run={run_id}"
    log.info("videos.trigger_build_only: spawning for %s/%s", slug, run_id)
    try:
        subprocess.Popen(  # noqa: S602
            ["sh", "-c", chain],
            cwd=str(_root()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        r.delete(_busy_key(slug, run_id), _started_key(slug, run_id))
        return False
    return True


def trigger_rerender(slug: str, run_id: str, *, needs_hydrate: bool = False) -> bool:
    """Run hydrate + render + build-clip-explorer in the background."""
    if not is_valid_slug(slug) or not is_valid_run_id(run_id):
        raise ValueError(f"Invalid slug or run_id: {slug!r} / {run_id!r}")
    r = _get_redis()
    acquired = r.set(_busy_key(slug, run_id), "1", nx=True, ex=_RENDER_BUSY_TTL_SECONDS)
    if not acquired:
        return False
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    r.set(_started_key(slug, run_id), now, ex=_RENDER_BUSY_TTL_SECONDS)

    parts = []
    if needs_hydrate:
        parts.append(f"npm run hydrate -- --program={slug}")
    parts.append(f"npm run render -- --program={slug} --run={run_id} --draft")
    parts.append(f"npm run build-clip-explorer -- --program={slug} --run={run_id}")
    chain = " && ".join(parts)
    log.info("videos.trigger_rerender: spawning for %s/%s (needs_hydrate=%s)", slug, run_id, needs_hydrate)
    try:
        subprocess.Popen(  # noqa: S602
            ["sh", "-c", chain],
            cwd=str(_root()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        r.delete(_busy_key(slug, run_id), _started_key(slug, run_id))
        return False
    return True


def render_status(slug: str, run_id: str) -> dict[str, Any]:
    r = _get_redis()
    busy = bool(r.get(_busy_key(slug, run_id)))
    started = r.get(_started_key(slug, run_id))
    if isinstance(started, bytes):
        started = started.decode("utf-8")
    return {"program_slug": slug, "run_id": run_id, "busy": busy, "started_at": started}


# ---------------------------------------------------------------------------
# Library parsing
# ---------------------------------------------------------------------------


_CARD_BLOCK_RE = re.compile(
    r'<div class="lib-card">([\s\S]*?)</div>\s*</div>(?=\s*(?:<div class="lib-card"|</div>|\Z))'
)
_ALIAS_RE = re.compile(r"<h3>@([^<]+)</h3>")
_SRC_RE = re.compile(r'<video src="([^"]+)"')
_META_RE = re.compile(r"<span>([\d.]+)s · ([\dx]+)</span>")
_USED_IN_RE = re.compile(r"lib-tag used-in[^>]*>([^<]+)")


def parse_library_html(html: str) -> list[dict[str, Any]]:
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


def load_library_entries(slug: str, run_id: str) -> list[dict[str, Any]]:
    lib = explorer_dir(slug, run_id) / "library.html"
    if not lib.exists():
        return []
    return parse_library_html(lib.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Explorer HTML rewriting
# ---------------------------------------------------------------------------


def rewrite_explorer_html(html: str, *, prefix: str, csrf_cookie_name: str) -> str:
    """Rewrite root-absolute paths to page-relative + inject CSRF + dark theme."""
    _ = prefix

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

    theme = """
<style id="ace-web-dark-theme">
:root {
  --paper: #0e0f12 !important;
  --paper-2: #161821 !important;
  --ink: #f3f4f6 !important;
  --ink-2: #e5e7eb !important;
  --ink-3: #cbd2dd !important;
  --line: #262833 !important;
  --rule: #353846 !important;
  --indigo-soft: #1d2540 !important;
  --sky-tint: #1a2030 !important;
  --muted: #9ca3af !important;
}
html, body { background: #0e0f12; color: #e5e7eb; }
.lib-card,
.range-row,
.nav-tabs a:not(.active),
[data-trim],
.card,
.assignments,
.beat,
.narration-edit,
.section-panel,
.no-asset { background: #161821 !important; border-color: #262833 !important; color: #e5e7eb !important; }
.section-stat { background: #0e0f12 !important; border-color: #262833 !important; color: #e5e7eb !important; }
.section-stat-caption { color: #e5e7eb !important; }
.section-brand-value { color: #f3f4f6 !important; }
.lead { background: linear-gradient(120deg, #161821 0%, #1a2030 100%) !important; color: #e5e7eb !important; }
.lib-meta code { background: #0e0f12 !important; color: #cbd2dd !important; }
.lib-placeholder { background: #0e0f12 !important; color: #9ca3af !important; }
input[type="text"], textarea, input[type="range"] { background: #0e0f12 !important; color: #e5e7eb !important; border-color: #262833 !important; }
.range-row button.btn-save-range,
.trim-save,
.nav-tabs a.active { color: #fff !important; }
.narration-edit-body { color: #f3f4f6 !important; }
.trim-bar { background: linear-gradient(180deg, #0e0f12 0%, #161821 100%) !important; }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: #2a2c34; border-radius: 6px; }
::-webkit-scrollbar-track { background: #0e0f12; }
</style>
"""

    return html.replace("<head>", "<head>" + wrapper + theme, 1)
