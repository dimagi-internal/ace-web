"""Filesystem + subprocess service layer for the videos surface.

**Source of truth = Drive.** Each workspace's spec.yaml files live in
its Drive root under ``videos/<program-slug>/runs/<run-id>/spec.yaml``.
The local FS at ``ACE_VIDEOS_ROOT/programs/...`` is render scratch:
``trigger_rerender`` stages the latest spec from Drive to local just
before kicking off the Node toolchain. Renders themselves write to
local (output.mp4, explorer/) and stay local for now — uploading the
rendered artifacts back to Drive is a follow-up.

Apart from spec.yaml, three things still live on local disk only and
will move to Drive in subsequent passes:
- the rendered output.mp4 (per run)
- the built explorer/ tree (per run)
- the per-program feedback.md log
- the ElevenLabs voiceover cache (assets/audio/) + music bed

YAML I/O uses ruamel.yaml so we round-trip with comments preserved.
"""
from __future__ import annotations

import datetime as dt
import io
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

from apps.videos import drive
from apps.workspaces.models import Workspace

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
    return bool(_SLUG_RE.match(slug))


def is_valid_run_id(run_id: str) -> bool:
    return bool(_RUN_RE.match(run_id))


# ---------------------------------------------------------------------------
# Local paths — kept for render scratch + outputs
# ---------------------------------------------------------------------------


def _root() -> Path:
    """connect-videos project root (where npm scripts are invoked)."""
    return Path(settings.ACE_VIDEOS_ROOT)


def program_dir(slug: str) -> Path:
    return _root() / "programs" / slug


def runs_dir(slug: str) -> Path:
    return program_dir(slug) / "runs"


def run_dir(slug: str, run_id: str) -> Path:
    return runs_dir(slug) / run_id


def spec_path(slug: str, run_id: str) -> Path:
    """LOCAL path where spec.yaml gets staged before a render. Drive is
    the source of truth; this is the npm toolchain's scratch."""
    return run_dir(slug, run_id) / "spec.yaml"


def output_path(slug: str, run_id: str) -> Path:
    return run_dir(slug, run_id) / "output.mp4"


def explorer_dir(slug: str, run_id: str) -> Path:
    return run_dir(slug, run_id) / "explorer"


def feedback_path(slug: str, run_id: str) -> Path:
    return explorer_dir(slug, run_id) / "feedback.md"


def drive_spec_display(slug: str, run_id: str) -> str:
    """Human-readable Drive path for UI display (not a filesystem path)."""
    return f"videos/{slug}/runs/{run_id}/spec.yaml"


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    return y


def _dump_yaml(doc: Any) -> str:
    """Serialize a YAML doc back to a string preserving formatting."""
    buf = io.StringIO()
    _yaml().dump(doc, buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Drive client / layout resolution
#
# ``client_for`` and ``layout_for`` are tiny wrappers so tests can
# monkeypatch ``apps.videos.drive.client_for_workspace`` to return a
# FakeDriveClient.
# ---------------------------------------------------------------------------


def client_for(workspace: Workspace):
    return drive.client_for_workspace(workspace)


def layout_for(workspace: Workspace, client=None):
    if client is None:
        client = client_for(workspace)
    return drive.resolve_layout(workspace, client), client


# ---------------------------------------------------------------------------
# Runs discovery
# ---------------------------------------------------------------------------


def list_run_ids(workspace: Workspace, slug: str) -> list[str]:
    layout, client = layout_for(workspace)
    return drive.list_run_ids(layout, client, slug)


def latest_run_id(workspace: Workspace, slug: str) -> str | None:
    ids = list_run_ids(workspace, slug)
    return ids[-1] if ids else None


def next_run_id(workspace: Workspace, slug: str) -> str:
    ids = list_run_ids(workspace, slug)
    if not ids:
        return "run-001"
    n = int(ids[-1].removeprefix("run-"))
    return f"run-{n + 1:03d}"


# ---------------------------------------------------------------------------
# ProgramRecord — the loaded-spec value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProgramRecord:
    slug: str
    run_id: str
    workspace_slug: str | None
    raw: dict[str, Any]
    yaml_path: str   # Drive display path: "videos/<slug>/runs/<run-id>/spec.yaml"

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


def _record_from_yaml(slug: str, run_id: str, spec_yaml: str) -> ProgramRecord | None:
    try:
        data = _yaml().load(spec_yaml)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    ws = data.get("workspace")
    return ProgramRecord(
        slug=slug,
        run_id=run_id,
        workspace_slug=str(ws) if ws else None,
        raw=dict(data),
        yaml_path=drive_spec_display(slug, run_id),
    )


def load_program_run(workspace: Workspace, slug: str, run_id: str) -> ProgramRecord | None:
    """Load the spec.yaml for one specific run from Drive."""
    if not is_valid_slug(slug) or not is_valid_run_id(run_id):
        return None
    layout, client = layout_for(workspace)
    spec_yaml = drive.read_spec(layout, client, slug, run_id)
    if spec_yaml is None:
        return None
    return _record_from_yaml(slug, run_id, spec_yaml)


def load_program(workspace: Workspace, slug: str, run_id: str | None = None) -> ProgramRecord | None:
    """Load a program — defaults to its latest run when run_id is None."""
    if not is_valid_slug(slug):
        return None
    rid = run_id or latest_run_id(workspace, slug)
    if rid is None:
        return None
    return load_program_run(workspace, slug, rid)


def iter_programs(workspace: Workspace) -> Iterable[ProgramRecord]:
    """Yield the latest run of every program under videos/."""
    layout, client = layout_for(workspace)
    for slug in drive.list_program_slugs(layout, client):
        rid = drive.latest_run_id(layout, client, slug)
        if rid is None:
            continue
        spec_yaml = drive.read_spec(layout, client, slug, rid)
        if spec_yaml is None:
            continue
        rec = _record_from_yaml(slug, rid, spec_yaml)
        if rec is not None:
            yield rec


def list_programs_for_workspace(workspace: Workspace) -> list[ProgramRecord]:
    """Latest-run record per program in this workspace."""
    return [
        p for p in iter_programs(workspace)
        if p.workspace_slug == workspace.slug
    ]


# ---------------------------------------------------------------------------
# Creates / writes
# ---------------------------------------------------------------------------


def create_program_from_spec(workspace: Workspace, slug: str, spec_yaml: str) -> str:
    """Create programs/<slug>/runs/run-001/spec.yaml in Drive.

    Validates: slug shape, slug uniqueness in workspace, body parses as
    a YAML mapping, slug + workspace fields inside spec_yaml match the
    target. Returns the Drive file id of the new spec.yaml.

    Raises ``ValueError`` (validation) / ``FileExistsError`` (collision).
    """
    if not is_valid_slug(slug):
        raise ValueError(f"Invalid program slug: {slug!r}")

    try:
        doc = _yaml().load(spec_yaml)
    except Exception as e:
        raise ValueError(f"spec_yaml is not valid YAML: {e}") from e
    if not isinstance(doc, dict):
        raise ValueError("spec_yaml must parse to a YAML mapping at the top level")
    if doc.get("slug") != slug:
        raise ValueError(
            f"spec_yaml.slug ({doc.get('slug')!r}) must match the URL slug ({slug!r})"
        )
    if doc.get("workspace") != workspace.slug:
        raise ValueError(
            f"spec_yaml.workspace ({doc.get('workspace')!r}) must match the URL workspace ({workspace.slug!r})"
        )

    layout, client = layout_for(workspace)
    existing = drive.program_folder_id(layout, client, slug)
    if existing is not None:
        raise FileExistsError(
            f"Program already exists in Drive: videos/{slug}/"
        )
    return drive.write_spec(layout, client, slug, "run-001", spec_yaml)


def copy_run(workspace: Workspace, slug: str, from_run_id: str) -> str:
    """Snapshot a run's spec.yaml into the next ``run-NNN`` in Drive.
    Both runs stay mutable — save-as, not fork.
    """
    layout, client = layout_for(workspace)
    src_yaml = drive.read_spec(layout, client, slug, from_run_id)
    if src_yaml is None:
        raise FileNotFoundError(f"Source run not found: videos/{slug}/runs/{from_run_id}")
    new_id = drive.next_run_id(layout, client, slug)
    drive.write_spec(layout, client, slug, new_id, src_yaml)
    return new_id


# ---------------------------------------------------------------------------
# Apply-edit (yaml mutation ops, mirror explore.ts::applyEdit)
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


def apply_edit(workspace: Workspace, slug: str, run_id: str, body: dict[str, Any]) -> EditResult:
    """Apply one of four ops to the run's spec.yaml in Drive (round-trip
    via ruamel.yaml to preserve comments).
    """
    layout, client = layout_for(workspace)
    spec_yaml = drive.read_spec(layout, client, slug, run_id)
    if spec_yaml is None:
        return EditResult(False, f"Spec not found for {slug}/{run_id}")

    y = _yaml()
    doc = y.load(spec_yaml)
    op = body.get("op")

    def _save() -> None:
        drive.write_spec(layout, client, slug, run_id, _dump_yaml(doc))

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
            _save()
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
            _save()
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
            _save()
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
        _save()
        return EditResult(True, f"Updated narration.by_beat.{beat_id}")

    return EditResult(False, f"Unknown op or missing args: {op!r}")


# ---------------------------------------------------------------------------
# Render triggers — stage Drive → local, then npm
# ---------------------------------------------------------------------------


_RENDER_BUSY_TTL_SECONDS = 60 * 60


def _busy_key(slug: str, run_id: str) -> str:
    return f"videos:render:{slug}:{run_id}:busy"


def _started_key(slug: str, run_id: str) -> str:
    return f"videos:render:{slug}:{run_id}:started_at"


def _stage_spec(workspace: Workspace, slug: str, run_id: str) -> None:
    """Pull spec.yaml from Drive and write it to the local scratch path
    so the npm toolchain sees the latest content."""
    layout, client = layout_for(workspace)
    drive.stage_spec_locally(layout, client, slug, run_id, _root())


def trigger_build_only(workspace: Workspace, slug: str, run_id: str) -> bool:
    """Spawn build-clip-explorer (no render). Sub-second."""
    if not is_valid_slug(slug) or not is_valid_run_id(run_id):
        raise ValueError(f"Invalid slug or run_id: {slug!r} / {run_id!r}")
    r = _get_redis()
    acquired = r.set(_busy_key(slug, run_id), "1", nx=True, ex=_RENDER_BUSY_TTL_SECONDS)
    if not acquired:
        return False
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    r.set(_started_key(slug, run_id), now, ex=_RENDER_BUSY_TTL_SECONDS)
    try:
        _stage_spec(workspace, slug, run_id)
    except Exception as e:
        log.warning("videos.trigger_build_only: staging failed for %s/%s: %s", slug, run_id, e)
        r.delete(_busy_key(slug, run_id), _started_key(slug, run_id))
        return False
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


def trigger_rerender(workspace: Workspace, slug: str, run_id: str, *, needs_hydrate: bool = False) -> bool:
    """Stage spec from Drive → local; spawn hydrate + render +
    build-clip-explorer in the background."""
    if not is_valid_slug(slug) or not is_valid_run_id(run_id):
        raise ValueError(f"Invalid slug or run_id: {slug!r} / {run_id!r}")
    r = _get_redis()
    acquired = r.set(_busy_key(slug, run_id), "1", nx=True, ex=_RENDER_BUSY_TTL_SECONDS)
    if not acquired:
        return False
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    r.set(_started_key(slug, run_id), now, ex=_RENDER_BUSY_TTL_SECONDS)
    try:
        _stage_spec(workspace, slug, run_id)
    except Exception as e:
        log.warning("videos.trigger_rerender: staging failed for %s/%s: %s", slug, run_id, e)
        r.delete(_busy_key(slug, run_id), _started_key(slug, run_id))
        return False
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
# Library parsing — reads local explorer/library.html (a render artifact)
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
# Explorer HTML rewriting (unchanged from prior)
# ---------------------------------------------------------------------------


def rewrite_explorer_html(html: str, *, prefix: str, csrf_cookie_name: str) -> str:
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
