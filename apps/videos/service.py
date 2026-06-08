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

from apps.videos import cache, drive
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


def qa_frames_dir(slug: str, run_id: str) -> Path:
    """Local dir where the QA probe writes per-beat preview PNGs after each
    render. The probe seeks ~the middle of each beat, captures a frame, and
    writes it as ``<beat_id>.png``. Used by the editor's GlobalTemplateWidget
    (and any future thumbnail surface) to show "what the rendered template
    actually looks like" without re-running the renderer."""
    return run_dir(slug, run_id) / "qa-frames"


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
    cached = cache.get_runs(workspace.slug, slug)
    if cached is not None:
        return cached
    layout, client = layout_for(workspace)
    ids = drive.list_run_ids(layout, client, slug)
    cache.set_runs(workspace.slug, slug, ids)
    return ids


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
    """Load the spec.yaml for one specific run from Drive (cache-aware)."""
    if not is_valid_slug(slug) or not is_valid_run_id(run_id):
        return None
    cached = cache.get_spec(workspace.slug, slug, run_id)
    if cached is not None:
        return _record_from_yaml(slug, run_id, cached)
    layout, client = layout_for(workspace)
    spec_yaml = drive.read_spec(layout, client, slug, run_id)
    if spec_yaml is None:
        return None
    cache.set_spec(workspace.slug, slug, run_id, spec_yaml)
    return _record_from_yaml(slug, run_id, spec_yaml)


def read_parsed_spec(workspace: Workspace, slug: str, run_id: str) -> dict | None:
    """Return the spec.yaml parsed via ruamel (round-trip safe), with the
    default beat list merged in. None if the spec doesn't exist.

    The per-run spec.yaml only carries `beat_overrides` (seconds tweaks) —
    the canonical beat list (id/kind/seconds for the 8 narrative units)
    lives in `programs/_defaults.yaml`. The React beat editor needs the
    resolved list to render. We merge here so the frontend stays simple.
    """
    if not is_valid_slug(slug) or not is_valid_run_id(run_id):
        return None
    layout, client = layout_for(workspace)
    raw = drive.read_spec(layout, client, slug, run_id)
    if raw is None:
        return None
    try:
        parsed = _yaml().load(raw)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    # Resolve defaults' beats + apply per-run overrides.
    if "beats" not in parsed:
        parsed["beats"] = _resolved_beats(parsed.get("beat_overrides") or {})
    # Scrub ruamel's round-trip wrappers (ScalarFloat / ScalarInt /
    # CommentedMap / CommentedSeq) to plain Python types. orjson refuses
    # to serialize float/int subclasses, so the moment a trim edit writes
    # `start_seconds: 8.0` and we re-read the spec, GET /runs/<id> 500s
    # with "Type is not JSON serializable: ScalarFloat". CommentedMap
    # and CommentedSeq inherit dict/list and serialize fine on their
    # own, but their nested values still need recursion. Done here at
    # the read boundary so callers downstream get vanilla Python dicts.
    return _scrub_ruamel(parsed)


def _scrub_ruamel(node: Any) -> Any:
    """Recursively unwrap ruamel.yaml round-trip types to plain
    Python. Safe to call on any nested dict/list/scalar structure."""
    if isinstance(node, dict):
        return {k: _scrub_ruamel(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_scrub_ruamel(v) for v in node]
    # bool must come before int (bool is a subclass of int)
    if isinstance(node, bool):
        return bool(node)
    if isinstance(node, float):
        return float(node)
    if isinstance(node, int):
        return int(node)
    return node


def _resolved_beats(overrides: dict) -> list[dict]:
    """Read `programs/_defaults.yaml` and apply per-run beat_overrides.

    Returns a list of {id, kind, seconds} dicts in declaration order.
    Empty list if defaults can't be read (the editor falls back to a no-
    beats view rather than 500).
    """
    from django.conf import settings

    defaults_path = Path(settings.ACE_VIDEOS_ROOT) / "programs" / "_defaults.yaml"
    if not defaults_path.is_file():
        return []
    try:
        doc = _yaml().load(defaults_path.read_text())
    except Exception:
        return []
    out: list[dict] = []
    for b in (doc.get("beats") or []):
        if not isinstance(b, dict):
            continue
        beat_id = b.get("id")
        if not beat_id:
            continue
        override = overrides.get(beat_id) if isinstance(overrides, dict) else None
        out.append({
            "id": beat_id,
            "kind": b.get("kind", ""),
            "seconds": float((override or {}).get("seconds", b.get("seconds", 0))),
        })
    return out


def load_program(workspace: Workspace, slug: str, run_id: str | None = None) -> ProgramRecord | None:
    """Load a program — defaults to its latest run when run_id is None."""
    if not is_valid_slug(slug):
        return None
    rid = run_id or latest_run_id(workspace, slug)
    if rid is None:
        return None
    return load_program_run(workspace, slug, rid)


def iter_programs(workspace: Workspace) -> Iterable[ProgramRecord]:
    """Yield the latest run of every program under videos/ (cache-aware).

    Three cache layers:
      - per-workspace slug list (videos:slugs:<ws>)
      - per-program run list (videos:runs:<ws>:<slug>)
      - per-run spec content (videos:spec:<ws>:<slug>:<run-id>)

    On a warm cache this is zero Drive calls.
    """
    cached_slugs = cache.get_slugs(workspace.slug)
    if cached_slugs is not None:
        slugs = cached_slugs
    else:
        layout, client = layout_for(workspace)
        slugs = drive.list_program_slugs(layout, client)
        cache.set_slugs(workspace.slug, slugs)

    for slug in slugs:
        rid = latest_run_id(workspace, slug)
        if rid is None:
            continue
        rec = load_program_run(workspace, slug, rid)
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


def validate_spec_structure(spec_yaml: str) -> dict:
    """Parse spec_yaml and verify it is a YAML mapping with slug + workspace.

    Returns the parsed dict on success.  Raises ``ValueError`` with a
    human-readable message on any structural failure.  Used by both
    ``create_program_from_spec`` (which then adds slug/workspace match
    checks) and ``apps.videos.templates.save_template`` (which validates
    an example spec before persisting it to Drive so saved examples always
    render without further edits).
    """
    try:
        doc = _yaml().load(spec_yaml)
    except Exception as e:
        raise ValueError(f"spec_yaml is not valid YAML: {e}") from e
    if not isinstance(doc, dict):
        raise ValueError("spec_yaml must parse to a YAML mapping at the top level")
    if not doc.get("slug"):
        raise ValueError("spec_yaml must contain a non-empty 'slug' field")
    if not doc.get("workspace"):
        raise ValueError("spec_yaml must contain a non-empty 'workspace' field")
    return doc


def create_program_from_spec(workspace: Workspace, slug: str, spec_yaml: str) -> str:
    """Create programs/<slug>/runs/run-001/spec.yaml in Drive.

    Validates: slug shape, slug uniqueness in workspace, body parses as
    a YAML mapping, slug + workspace fields inside spec_yaml match the
    target. Returns the Drive file id of the new spec.yaml.

    Raises ``ValueError`` (validation) / ``FileExistsError`` (collision).
    """
    if not is_valid_slug(slug):
        raise ValueError(f"Invalid program slug: {slug!r}")

    doc = validate_spec_structure(spec_yaml)
    if doc.get("slug") != slug:
        raise ValueError(
            f"spec_yaml.slug ({doc.get('slug')!r}) must match the URL slug ({slug!r})"
        )
    if doc.get("workspace") != workspace.slug:
        raise ValueError(
            f"spec_yaml.workspace ({doc.get('workspace')!r}) must match the URL workspace ({workspace.slug!r})"
        )

    # Auto-derive narration.script from by_beat if the spec author left
    # it empty. The Remotion renderer aborts if narration.script is
    # empty (its precondition check), but the actual VO synthesis uses
    # by_beat when present — so script just needs to be non-empty
    # plausible text. Joining the per-beat values is the obvious thing
    # and saves the agent from writing the same content twice.
    spec_yaml = _autofill_narration_script(spec_yaml, doc)

    layout, client = layout_for(workspace)
    existing = drive.program_folder_id(layout, client, slug)
    if existing is not None:
        raise FileExistsError(
            f"Program already exists in Drive: videos/{slug}/"
        )
    file_id = drive.write_spec(layout, client, slug, "run-001", spec_yaml)
    cache.invalidate_program(workspace.slug, slug)
    cache.set_spec(workspace.slug, slug, "run-001", spec_yaml)
    return file_id


def _autofill_narration_script(spec_yaml: str, doc: dict) -> str:
    """If narration.script is empty but narration.by_beat is populated,
    join the per-beat values into a flowing script. Returns the spec
    text with the script substituted in (or unchanged if not needed).

    Round-trips through ruamel.yaml to preserve comments and quoting
    style on every other field. Only narration.script changes.
    """
    narration = doc.get("narration") if isinstance(doc, dict) else None
    if not isinstance(narration, dict):
        return spec_yaml
    script = narration.get("script")
    if isinstance(script, str) and script.strip():
        return spec_yaml  # author provided a script, respect it
    by_beat = narration.get("by_beat")
    if not isinstance(by_beat, dict):
        return spec_yaml
    parts = [str(v).strip() for v in by_beat.values() if str(v).strip()]
    if not parts:
        return spec_yaml
    joined = "\n".join(parts) + "\n"
    # Round-trip preserves quotes/comments on every other key.
    rt = YAML()
    rt.preserve_quotes = True
    rt.width = 4096
    parsed = rt.load(spec_yaml)
    parsed["narration"]["script"] = joined
    buf = io.StringIO()
    rt.dump(parsed, buf)
    return buf.getvalue()


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
    cache.invalidate_runs(workspace.slug, slug)
    cache.set_spec(workspace.slug, slug, new_id, src_yaml)
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


def _apply_single_op(
    doc: Any,
    op: dict[str, Any],
    workspace: Workspace | None = None,
) -> EditResult:
    """Apply one edit op to an in-memory ruamel YAML doc. Pure mutation,
    no I/O **except** the set-clip-asset op when given a ``library:``
    ref — that path queries VideoLibraryEntry to resolve the gdrive id
    and auto-add a manifest entry. Returns ok=False on validation
    failure (caller decides whether to abort the whole batch).

    `workspace` is needed only by the library-ref code path; other ops
    accept None.
    """
    name = op.get("op")

    if name in {"set-clip-start", "set-clip-trim", "set-clip-asset"}:
        index = op.get("index")
        kind = op.get("kind")
        if not isinstance(index, int):
            return EditResult(False, "index must be an integer")
        keys = _clip_path_keys(kind, index)
        node = _get_in(doc, keys)

        if name == "set-clip-start":
            start_seconds = op.get("start_seconds")
            if not isinstance(start_seconds, (int, float)):
                return EditResult(False, "start_seconds must be a number")
            if isinstance(node, str):
                _set_in(doc, keys, {"asset": node, "start_seconds": float(start_seconds)})
            elif isinstance(node, dict):
                node["start_seconds"] = float(start_seconds)
            else:
                return EditResult(False, f"Could not find {kind}[{index}]")
            return EditResult(True, f"Set {kind}[{index}].start_seconds = {start_seconds}")

        if name == "set-clip-trim":
            start_seconds = op.get("start_seconds")
            duration_seconds = op.get("duration_seconds")
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
            return EditResult(True, f"Set {kind}[{index}] trim window")

        if name == "set-clip-asset":
            alias = op.get("alias")
            lib_ref = op.get("ref")
            # Two entry shapes:
            #   {alias: "mobile-learn"}                    → uses an existing
            #     spec.manifest alias verbatim
            #   {ref: "library:video/<sub>/<filename>.mp4"} → looks up the
            #     gdrive id in the workspace's VideoLibraryEntry, auto-adds
            #     a manifest entry if one doesn't exist, then sets the slot
            #     to @<derived-alias>. The picker uses this so users can
            #     pick any workspace-library clip in one click.
            if (not alias) and isinstance(lib_ref, str) and lib_ref.startswith("library:video/"):
                if workspace is None:
                    return EditResult(False, "library ref requires workspace context")
                # Parse "library:video/<sub>/<filename>" — tolerate
                # trailing extension or not.
                tail = lib_ref[len("library:video/"):]
                parts = tail.split("/", 1)
                if len(parts) != 2:
                    return EditResult(False, f"malformed ref: {lib_ref!r}")
                subfolder, filename = parts
                from apps.videos.models import VideoLibraryEntry
                try:
                    entry = VideoLibraryEntry.objects.get(
                        workspace=workspace, subfolder=subfolder, filename=filename,
                    )
                except VideoLibraryEntry.DoesNotExist:
                    return EditResult(
                        False,
                        f"library entry not found: {subfolder}/{filename}",
                    )
                # Derive an alias from filename: strip extension. The
                # filename was chosen at library-seed time to match the
                # alias convention (kebab-case, no spaces) so this is a
                # clean transform.
                stem = filename.rsplit(".", 1)[0]
                ext = (
                    filename.rsplit(".", 1)[1] if "." in filename else "mp4"
                )
                alias = stem
                manifest = doc.setdefault("manifest", {})
                if alias not in manifest:
                    manifest[alias] = f"gdrive:{entry.drive_id}.{ext}"
            if not isinstance(alias, str) or not alias:
                return EditResult(False, "alias or library ref required")
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
            return EditResult(True, f"Swapped {kind}[{index}] -> @{alias}")

    if name == "set-narration":
        beat_id = op.get("beatId")
        text = op.get("text")
        if not isinstance(beat_id, str) or not beat_id:
            return EditResult(False, "beatId must be a non-empty string")
        if not isinstance(text, str):
            return EditResult(False, "text must be a string")
        narration = doc.setdefault("narration", {})
        by_beat = narration.setdefault("by_beat", {})
        by_beat[beat_id] = text
        return EditResult(True, f"Updated narration.by_beat.{beat_id}")

    if name == "set-stat":
        import re
        path = op.get("path")
        if not isinstance(path, str):
            return EditResult(False, "path must be a string")

        if path == "problem":
            node = doc.get("problem")
            if not isinstance(node, dict):
                return EditResult(False, "spec has no `problem` section")
        else:
            m = re.fullmatch(r"impact\[(\d+)\]", path)
            if not m:
                return EditResult(False, f"unknown path {path!r}; expected 'problem' or 'impact[N]'")
            idx = int(m.group(1))
            impact = doc.get("impact")
            if not isinstance(impact, list):
                return EditResult(False, "spec has no `impact` section")
            if idx < 0 or idx >= len(impact):
                return EditResult(False, f"impact index {idx} out of range (len={len(impact)})")
            node = impact[idx]
            if not isinstance(node, dict):
                return EditResult(False, f"impact[{idx}] is not a mapping")

        for field in ("big", "caption"):
            val = op.get(field)
            if val is None:
                continue  # field absent → no change
            if not isinstance(val, str):
                return EditResult(False, f"{field} must be a string")
            node[field] = val

        # `source` has tri-state semantics: absent → no change, "" → clear, str → set
        if "source" in op:
            val = op["source"]
            if val is None or val == "":
                node.pop("source", None)
            elif isinstance(val, str):
                node["source"] = val
            else:
                return EditResult(False, "source must be a string")

        return EditResult(True, f"Updated stat {path}")

    if name == "set-global-template":
        # Per-program override of the global template. Writes under
        # spec.global_template; the renderer's resolveGlobalTemplate()
        # in Root.tsx prefers spec.global_template over
        # programs/_defaults.yaml > global_template at render time.
        # Absent fields mean "no change to that field". Pass empty
        # string to tagline OR an empty list to cycle_steps to clear
        # that override (falls back to global default).
        #
        # Renamed from `spec.brand` 2026-05-21 to match the editor UI
        # label ("Global template"). Any pre-rename `spec.brand` block
        # is migrated to `spec.global_template` on first edit so the
        # spec doesn't carry both keys.
        if "brand" in doc and "global_template" not in doc:
            doc["global_template"] = doc.pop("brand")
        else:
            # Drop any stale legacy key once new key exists.
            doc.pop("brand", None)
        gt = doc.setdefault("global_template", {})
        tagline = op.get("tagline")
        cycle_steps = op.get("cycle_steps")
        any_change = False
        if tagline is not None:
            if not isinstance(tagline, str):
                return EditResult(False, "tagline must be a string")
            if tagline == "":
                gt.pop("tagline", None)
            else:
                gt["tagline"] = tagline
            any_change = True
        if cycle_steps is not None:
            if not isinstance(cycle_steps, list):
                return EditResult(False, "cycle_steps must be a list")
            if len(cycle_steps) == 0:
                gt.pop("cycle_steps", None)
            else:
                if len(cycle_steps) != 4:
                    return EditResult(False, "cycle_steps must have exactly 4 entries")
                if not all(isinstance(s, str) and s for s in cycle_steps):
                    return EditResult(False, "every cycle_steps entry must be a non-empty string")
                gt["cycle_steps"] = list(cycle_steps)
            any_change = True
        if not any_change:
            return EditResult(False, "set-global-template requires tagline or cycle_steps")
        # If the section is now empty (all overrides cleared), drop it.
        if not gt:
            doc.pop("global_template", None)
        return EditResult(True, "Updated program global-template override")

    if name == "set-program-name":
        # Rename the program — writes spec.name. The Remotion <Handoff>
        # composition renders this directly ("Here's how that works for
        # <name>"), and the editor breadcrumb + program list also surface
        # it. Empty / whitespace-only is rejected; every program needs
        # a display name (the slug stays separate and isn't editable here).
        new_name = op.get("name")
        if not isinstance(new_name, str) or not new_name.strip():
            return EditResult(False, "name must be a non-empty string")
        doc["name"] = new_name.strip()
        return EditResult(True, "Renamed program")

    return EditResult(False, f"Unknown op: {name!r}")


def apply_edit(workspace: Workspace, slug: str, run_id: str, body: dict[str, Any]) -> EditResult:
    """Single-op edit — load, apply one op, save. Backward compat wrapper
    around `_apply_single_op`. Used by the existing `POST /edit` endpoint."""
    layout, client = layout_for(workspace)
    spec_yaml = drive.read_spec(layout, client, slug, run_id)
    if spec_yaml is None:
        return EditResult(False, f"Spec not found for {slug}/{run_id}")
    y = _yaml()
    doc = y.load(spec_yaml)
    result = _apply_single_op(doc, body)
    if not result.ok:
        return result
    new_yaml = _dump_yaml(doc)
    drive.write_spec(layout, client, slug, run_id, new_yaml)
    cache.set_spec(workspace.slug, slug, run_id, new_yaml)
    return result


@dataclass(frozen=True)
class BatchResult:
    ok: bool
    applied: int
    message: str


def apply_edit_batch(
    workspace: Workspace,
    slug: str,
    run_id: str,
    ops: list[dict[str, Any]],
) -> BatchResult:
    """Apply N edit ops to spec.yaml in one Drive round-trip. All-or-nothing:
    if any op fails validation, the doc is not saved and ``applied=0``.

    Empty batch is a no-op (returns ok=True, applied=0) with no Drive I/O.
    """
    if not ops:
        return BatchResult(True, 0, "no-op (empty batch)")

    layout, client = layout_for(workspace)
    spec_yaml = drive.read_spec(layout, client, slug, run_id)
    if spec_yaml is None:
        return BatchResult(False, 0, f"Spec not found for {slug}/{run_id}")

    y = _yaml()
    doc = y.load(spec_yaml)
    messages: list[str] = []
    for i, op in enumerate(ops):
        # Thread the workspace through so set-clip-asset with a library
        # ref can look up VideoLibraryEntry rows. Other ops ignore it.
        result = _apply_single_op(doc, op, workspace=workspace)
        if not result.ok:
            return BatchResult(False, 0, f"op[{i}] failed: {result.message}")
        messages.append(result.message)

    new_yaml = _dump_yaml(doc)
    drive.write_spec(layout, client, slug, run_id, new_yaml)
    cache.set_spec(workspace.slug, slug, run_id, new_yaml)
    return BatchResult(True, len(ops), "; ".join(messages))


# ---------------------------------------------------------------------------
# existing_content/ — shared binary assets (audio cache + music bed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExistingContentItem:
    """One file under `videos/existing_content/<subdir>/`."""
    subdir: str
    filename: str
    size_bytes: int
    drive_id: str
    modified_time: str | None = None


def list_existing_content(
    workspace: Workspace, subdir: str,
) -> list[ExistingContentItem]:
    """Enumerate files in `videos/existing_content/<subdir>/`. Used by
    the migration command to skip already-uploaded entries and by the
    render-time hydrator to know what to pull down."""
    if subdir not in drive.EXISTING_CONTENT_SUBDIRS:
        raise ValueError(
            f"Unknown existing_content subdir: {subdir}; "
            f"expected one of {drive.EXISTING_CONTENT_SUBDIRS}"
        )
    layout, client = layout_for(workspace)
    files = drive.list_existing_content(layout, client, subdir)
    return [
        ExistingContentItem(
            subdir=subdir, filename=f.name,
            size_bytes=f.size_bytes or 0,
            drive_id=f.id,
            modified_time=f.modified_time,
        )
        for f in files
    ]


def upload_existing_content(
    workspace: Workspace, subdir: str, filename: str,
    content: bytes, mime_type: str,
) -> str:
    """Idempotent upload. Returns the Drive file id."""
    if subdir not in drive.EXISTING_CONTENT_SUBDIRS:
        raise ValueError(
            f"Unknown existing_content subdir: {subdir}; "
            f"expected one of {drive.EXISTING_CONTENT_SUBDIRS}"
        )
    if "/" in filename or filename.startswith(".") or not filename:
        raise ValueError(f"Invalid filename: {filename!r}")
    layout, client = layout_for(workspace)
    return drive.upload_existing_content(
        layout, client, subdir, filename, content, mime_type,
    )


def read_existing_content(
    workspace: Workspace, subdir: str, filename: str,
) -> bytes | None:
    if subdir not in drive.EXISTING_CONTENT_SUBDIRS:
        return None
    layout, client = layout_for(workspace)
    return drive.read_existing_content(layout, client, subdir, filename)


def _local_existing_content_dir(subdir: str) -> Path:
    """Local mirror of Drive's `existing_content/<subdir>/`. Matches the
    Node toolchain's expected layout: assets/audio/ and assets/shared/."""
    return _root() / "assets" / subdir


def stage_existing_content_locally(workspace: Workspace) -> dict[str, int]:
    """Pull audio + shared assets from Drive into local
    `<videos_root>/assets/{audio,shared}/`.

    Source-of-truth precedence per asset type:

      audio:  videos/library/audio/   (new)  >>  videos/existing_content/audio/   (legacy)
      shared: videos/shared/          (new)  >>  videos/existing_content/shared/  (legacy)

    The legacy fallback is kept through Phase B of the relocation
    rollout; remove it in Phase C once the Drive move has run on every
    workspace and the dual-write code has been retired.

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


# ---------------------------------------------------------------------------
# Per-run render artifacts (output.mp4, explorer/, feedback.md) → Drive
# ---------------------------------------------------------------------------


def _tar_gz_explorer_dir(local_dir: Path) -> bytes:
    """Tarball + gzip an explorer directory into bytes for Drive upload.

    Archives the explorer tree as-is, recording symlinks AS symlinks
    rather than dereferencing them. The media/ subdir is full of
    relative symlinks into the hydrate cache
    (``~/.cache/connect-videos/<gdriveId>.<ext>``) that point at paths
    on the rendering host's filesystem. With ``dereference=True`` the
    tar follows them and FileNotFoundErrors out the moment publish
    runs in a context that can't see those host paths — which is
    every time publish runs in the Django container after a Mac
    render (``render_locally.py --publish``).

    With ``dereference=False`` the tar carries the symlinks as
    metadata. The receiving host extracts them as dangling symlinks
    and ``apps.videos.api._resolve_symlink_via_drive`` lazy-pulls
    each clip's bytes through the workspace SA on first request.
    Net: smaller archive, no host-FS coupling, Drive is the source of
    truth.
    """
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", dereference=False) as tar:
        # arcname="" so paths inside the archive are relative to the
        # explorer/ dir itself (index.html at root, media/ subfolder).
        tar.add(str(local_dir), arcname="")
    return buf.getvalue()


def _untar_gz_explorer_to_dir(payload: bytes, dest_dir: Path) -> None:
    """Restore an explorer.tar.gz onto local disk. Used by hosts that
    didn't render the run but want to serve the explorer iframe."""
    import io
    import tarfile

    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        tar.extractall(dest_dir, filter="data")


@dataclass(frozen=True)
class PublishResult:
    output_mp4_id: str | None = None
    explorer_archive_id: str | None = None
    feedback_id: str | None = None
    bytes_uploaded: int = 0


def publish_render_artifacts(
    workspace: Workspace, slug: str, run_id: str,
) -> PublishResult:
    """Push the per-run output.mp4 / explorer.tar.gz / feedback.md from
    local disk to Drive, then publish any newly-synthesized audio
    sidecars to the workspace's audio library.

    Called at the end of a successful render chain (and via the
    ``videos_publish_artifacts`` management command). Each artifact is
    optional — if the local file is missing, the corresponding upload
    is skipped silently. Replaces any existing copies in Drive.

    Audio library publishing is best-effort: a failure here logs a
    warning but doesn't fail the publish — the main artifacts are
    already in Drive.
    """
    if not is_valid_slug(slug) or not is_valid_run_id(run_id):
        raise ValueError(f"Invalid slug or run_id: {slug!r} / {run_id!r}")
    layout, client = layout_for(workspace)

    bytes_total = 0
    mp4_id: str | None = None
    archive_id: str | None = None
    feedback_id: str | None = None

    # Record file_id mappings as we publish so the file_cache reverse
    # index is populated even on the rendering host (otherwise the
    # rendering host's local copy would never receive invalidation
    # signals from Drive Changes for republishes done elsewhere).
    from apps.videos import file_cache  # noqa: PLC0415 — avoid circular at import time

    mp4_path = output_path(slug, run_id)
    if mp4_path.exists():
        content = mp4_path.read_bytes()
        mp4_id = drive.upload_output_mp4(layout, client, slug, run_id, content)
        bytes_total += len(content)
        log.info(
            "videos.publish: output.mp4 → drive id=%s size=%d", mp4_id, len(content),
        )
        file_cache.record(workspace.slug, slug, run_id, "output_mp4", mp4_id)

    exp_dir = explorer_dir(slug, run_id)
    if exp_dir.is_dir() and any(exp_dir.iterdir()):
        archive = _tar_gz_explorer_dir(exp_dir)
        archive_id = drive.upload_explorer_archive(
            layout, client, slug, run_id, archive,
        )
        bytes_total += len(archive)
        log.info(
            "videos.publish: explorer.tar.gz → drive id=%s size=%d",
            archive_id, len(archive),
        )
        file_cache.record(workspace.slug, slug, run_id, "explorer_archive", archive_id)

    feedback = feedback_path(slug, run_id)
    if feedback.exists():
        text = feedback.read_text(encoding="utf-8")
        feedback_id = drive.write_feedback(layout, client, slug, run_id, text)
        bytes_total += len(text.encode("utf-8"))
        log.info(
            "videos.publish: feedback.md → drive id=%s len=%d", feedback_id, len(text),
        )

    try:
        audio_counts = publish_audio_library_from_local(workspace)
        if audio_counts["uploaded_mp3"] or audio_counts["uploaded_json"]:
            log.info(
                "videos.publish: audio library +%d mp3 +%d json (db +%d created, %d updated)",
                audio_counts["uploaded_mp3"], audio_counts["uploaded_json"],
                audio_counts["db_created"], audio_counts["db_updated"],
            )
    except Exception as e:  # noqa: BLE001 — best-effort, never break publish
        log.warning("videos.publish: audio library push failed: %s", e)

    return PublishResult(
        output_mp4_id=mp4_id,
        explorer_archive_id=archive_id,
        feedback_id=feedback_id,
        bytes_uploaded=bytes_total,
    )


def publish_audio_library_from_local(workspace: Workspace) -> dict[str, int]:
    """Upload locally-synthesized audio (and sidecars) to the workspace's
    Drive ``library/audio/`` folder, then upsert ``AudioLibraryEntry``
    rows for what's there.

    The renderer's ElevenLabs synthesis writes ``<hash>.mp3`` +
    ``<hash>.json`` to ``<videos_root>/assets/audio/``. After a render
    completes, this pushes any pair not already in Drive up to
    ``library/audio/``. Idempotent on name match: if Drive already has
    ``<hash>.mp3`` we skip the mp3 upload (assume bytes match — synthesis
    is deterministic on (voice_id, model, text)).

    Returns ``{uploaded_mp3, uploaded_json, db_created, db_updated}``.
    """
    local_dir = _root() / "assets" / "audio"
    counts = {"uploaded_mp3": 0, "uploaded_json": 0, "db_created": 0, "db_updated": 0}
    if not local_dir.is_dir():
        return counts

    layout, client = layout_for(workspace)

    drive_files = {f.name for f in drive.list_audio_library_files(layout, client)}

    pairs: dict[str, dict[str, Path]] = {}
    for f in local_dir.iterdir():
        if not f.is_file():
            continue
        if f.suffix == ".mp3":
            pairs.setdefault(f.stem, {})["mp3"] = f
        elif f.suffix == ".json":
            pairs.setdefault(f.stem, {})["json"] = f

    for hash_, parts in pairs.items():
        mp3 = parts.get("mp3")
        json_file = parts.get("json")
        if mp3 is None:
            continue  # orphan sidecar locally — nothing to publish
        mp3_name = f"{hash_}.mp3"
        json_name = f"{hash_}.json"
        if mp3_name not in drive_files:
            drive.upload_library_file(
                layout, client, drive.LIBRARY_AUDIO,
                mp3_name, mp3.read_bytes(), "audio/mpeg",
            )
            counts["uploaded_mp3"] += 1
        if json_file is not None and json_name not in drive_files:
            drive.upload_library_file(
                layout, client, drive.LIBRARY_AUDIO,
                json_name, json_file.read_bytes(), "application/json",
            )
            counts["uploaded_json"] += 1

    if counts["uploaded_mp3"] or counts["uploaded_json"]:
        from apps.videos.library import sync as lib_sync
        sync_counts = lib_sync.sync_import_audio(workspace)
        counts["db_created"] = sync_counts["created"]
        counts["db_updated"] = sync_counts["updated"]

    return counts


def output_mp4_drive_link(workspace: Workspace, slug: str, run_id: str) -> str | None:
    """Drive webViewLink for the published output.mp4, or None if not
    published yet. Used by share / summary surfaces."""
    if not is_valid_slug(slug) or not is_valid_run_id(run_id):
        return None
    layout, client = layout_for(workspace)
    meta = drive.output_mp4_drive_meta(layout, client, slug, run_id)
    if meta is None:
        return None
    return meta.web_view_link or None


def read_feedback(
    workspace: Workspace, slug: str, run_id: str, *, allow_local_fallback: bool = True,
) -> str:
    """Read the per-run feedback log. Drive first; falls back to local
    disk only if Drive doesn't have it and the local file exists. New
    feedback always lands in Drive via ``append_feedback``."""
    if not is_valid_slug(slug) or not is_valid_run_id(run_id):
        return ""
    layout, client = layout_for(workspace)
    remote = drive.read_feedback(layout, client, slug, run_id)
    if remote is not None:
        return remote
    if allow_local_fallback:
        local = feedback_path(slug, run_id)
        if local.exists():
            return local.read_text(encoding="utf-8")
    return ""


def append_feedback(
    workspace: Workspace, slug: str, run_id: str, line: str,
) -> str:
    """Append a line to the run's feedback.md and return the full new
    content. Atomic at the level of one HTTP request — concurrent writers
    can still last-writer-wins (acceptable for a notes log)."""
    if not is_valid_slug(slug) or not is_valid_run_id(run_id):
        raise ValueError(f"Invalid slug or run_id: {slug!r} / {run_id!r}")
    layout, client = layout_for(workspace)
    current = drive.read_feedback(layout, client, slug, run_id) or ""
    new_content = current + line
    drive.write_feedback(layout, client, slug, run_id, new_content)
    return new_content


def stage_explorer_archive_locally(
    workspace: Workspace, slug: str, run_id: str,
) -> bool:
    """Pull explorer.tar.gz from Drive and extract over the local
    explorer/ dir. Returns True if extracted, False if nothing in Drive.

    Lets a fresh host serve the explorer iframe without re-rendering —
    handy when ace-web pods rotate or a teammate clones the repo and
    wants to view an already-rendered run.
    """
    if not is_valid_slug(slug) or not is_valid_run_id(run_id):
        return False
    layout, client = layout_for(workspace)
    payload = drive.read_explorer_archive(layout, client, slug, run_id)
    if payload is None:
        return False
    _untar_gz_explorer_to_dir(payload, explorer_dir(slug, run_id))
    return True


# ---------------------------------------------------------------------------
# Render triggers — stage Drive → local, then npm
# ---------------------------------------------------------------------------


_RENDER_BUSY_TTL_SECONDS = 60 * 60


def _busy_key(slug: str, run_id: str) -> str:
    return f"videos:render:{slug}:{run_id}:busy"


def _started_key(slug: str, run_id: str) -> str:
    return f"videos:render:{slug}:{run_id}:started_at"


def _rewrite_library_refs_in_spec(workspace: Workspace, spec_yaml: str) -> str:
    """Rewrite every ``library:<media>/[<sub>/]<file>`` manifest value to the
    equivalent ``gdrive:<id>.<ext>`` form, leaving non-library values alone.

    Performed on the local staged copy of spec.yaml before the renderer
    sees it. The Drive-side spec keeps the stable ``library:`` refs.
    Unresolvable refs are left as-is — the renderer will surface them as
    missing assets and the operator can fix the library entry.

    Uses ruamel.yaml for round-trip preservation of comments / order.
    """
    from io import StringIO

    from apps.videos.library import refs as lib_refs

    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    doc = yaml.load(spec_yaml)
    if not isinstance(doc, dict):
        return spec_yaml
    manifest = doc.get("manifest")
    if not isinstance(manifest, dict):
        return spec_yaml

    changed = False
    for alias, value in list(manifest.items()):
        if not isinstance(value, str) or not lib_refs.is_library_ref(value):
            continue
        try:
            resolved = lib_refs.resolve_library_ref(workspace, value)
        except lib_refs.LibraryRefError:
            log.warning(
                "videos: malformed library ref %r in manifest entry %r", value, alias
            )
            continue
        if resolved is None:
            log.info("videos: library ref %r not found; leaving as-is", value)
            continue
        ext = Path(resolved.parsed.filename).suffix.lstrip(".")
        if not ext:
            log.warning("videos: library ref %r has no extension; cannot rewrite", value)
            continue
        manifest[alias] = f"gdrive:{resolved.drive_id}.{ext}"
        changed = True

    if not changed:
        return spec_yaml
    buf = StringIO()
    yaml.dump(doc, buf)
    return buf.getvalue()


def _stage_spec(workspace: Workspace, slug: str, run_id: str) -> None:
    """Pull spec.yaml from Drive and write it to the local scratch path
    so the npm toolchain sees the latest content.

    Rewrites ``library:`` manifest refs to ``gdrive:<id>.<ext>`` on the
    way through — the renderer keeps parsing the stable ``gdrive:`` form.
    """
    layout, client = layout_for(workspace)
    target = drive.stage_spec_locally(layout, client, slug, run_id, _root())
    original = target.read_text(encoding="utf-8")
    rewritten = _rewrite_library_refs_in_spec(workspace, original)
    if rewritten != original:
        target.write_text(rewritten, encoding="utf-8")


def _manifest_cache_dir() -> Path:
    """Where the Node renderer's hydrate step expects gdrive: refs to
    land. Matches ``defaultCacheDir()`` in
    ``video-production/connect-videos/src/lib/asset-resolver.node.ts``
    (``~/.cache/connect-videos``).
    """
    return Path.home() / ".cache" / "connect-videos"


_GDRIVE_RE = re.compile(r"^gdrive:([A-Za-z0-9_\-]+)\.([A-Za-z0-9]+)$")


def prefetch_manifest_to_cache(
    workspace: Workspace, slug: str, run_id: str,
) -> dict[str, int]:
    """Walk the staged spec.yaml's ``manifest:`` and download any
    ``gdrive:<id>.<ext>`` ref not yet in the local render cache via the
    Drive SA client.

    The npm hydrate step otherwise expects an operator to have pulled
    each file via the ace-gdrive MCP first — fine for laptop dev, but
    blocks every render on labs where the server has the SA credentials
    in hand.

    Returns ``{downloaded, skipped, errored}`` counts.
    """
    staged = spec_path(slug, run_id)
    if not staged.exists():
        return {"downloaded": 0, "skipped": 0, "errored": 0}

    try:
        doc = YAML(typ="safe").load(staged.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("videos.prefetch: failed to parse %s: %s", staged, e)
        return {"downloaded": 0, "skipped": 0, "errored": 0}

    if not isinstance(doc, dict):
        return {"downloaded": 0, "skipped": 0, "errored": 0}
    manifest = doc.get("manifest") or {}
    if not isinstance(manifest, dict):
        return {"downloaded": 0, "skipped": 0, "errored": 0}

    cache_dir = _manifest_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    counts = {"downloaded": 0, "skipped": 0, "errored": 0}

    layout = None
    client = None
    for _alias, ref in manifest.items():
        if not isinstance(ref, str):
            continue
        m = _GDRIVE_RE.match(ref)
        if m is None:
            continue
        file_id, ext = m.group(1), m.group(2)
        target = cache_dir / f"{file_id}.{ext}"
        if target.exists() and target.stat().st_size > 0:
            counts["skipped"] += 1
            continue
        if client is None:
            layout, client = layout_for(workspace)
        try:
            content = client.get_binary(file_id)
        except Exception as e:  # noqa: BLE001 — Drive errors logged, render keeps going
            log.warning(
                "videos.prefetch: failed to fetch %s for %s/%s: %s",
                file_id, slug, run_id, e,
            )
            counts["errored"] += 1
            continue
        target.write_bytes(content)
        counts["downloaded"] += 1

    if counts["downloaded"] or counts["errored"]:
        log.info(
            "videos.prefetch: %s/%s downloaded=%d skipped=%d errored=%d",
            slug, run_id, counts["downloaded"], counts["skipped"], counts["errored"],
        )
    return counts


def _publish_artifacts_subcommand(
    workspace: Workspace, slug: str, run_id: str,
) -> str:
    """Build the shell substring that runs the publish-artifacts management
    command after a successful render. Slug + run_id are pre-validated by
    the caller (``trigger_rerender``) so the shell interpolation is safe.

    We prefer the venv python if it's around (local dev), otherwise the
    system python (Docker image has /usr/local/bin/python from uv)."""
    return (
        f"python manage.py videos_publish_artifacts "
        f"--workspace={workspace.slug} --program={slug} --run={run_id}"
    )


def render_log_path(slug: str, run_id: str) -> Path:
    """LOCAL path where the spawned render chain's stdout+stderr is captured.
    Persistent per-run; overwritten on each new render."""
    return run_dir(slug, run_id) / "render.log"


def _open_render_log(slug: str, run_id: str):
    """Open the run's render.log for writing (truncates any prior log).
    Returns a file handle the caller passes to subprocess.Popen as
    stdout/stderr. Any I/O error here is logged but doesn't fail the
    render — a render with no log is still better than no render."""
    log_path = render_log_path(slug, run_id)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        return log_path.open("wb")
    except OSError as e:
        log.warning("videos: failed to open render.log at %s: %s", log_path, e)
        return None


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
        stage_existing_content_locally(workspace)
    except Exception as e:
        log.warning("videos.trigger_build_only: staging failed for %s/%s: %s", slug, run_id, e)
        r.delete(_busy_key(slug, run_id), _started_key(slug, run_id))
        return False
    chain = f"npm run build-clip-explorer -- --program={slug} --run={run_id}"
    log.info("videos.trigger_build_only: spawning for %s/%s", slug, run_id)
    log_handle = _open_render_log(slug, run_id)
    try:
        subprocess.Popen(  # noqa: S602
            ["sh", "-c", chain],
            cwd=str(_root()),
            stdout=log_handle if log_handle else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if log_handle else subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        if log_handle:
            log_handle.close()
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
        stage_existing_content_locally(workspace)
        prefetch_manifest_to_cache(workspace, slug, run_id)
    except Exception as e:
        log.warning("videos.trigger_rerender: staging failed for %s/%s: %s", slug, run_id, e)
        r.delete(_busy_key(slug, run_id), _started_key(slug, run_id))
        return False
    parts = []
    if needs_hydrate:
        parts.append(f"npm run hydrate -- --program={slug}")
    parts.append(f"npm run render -- --program={slug} --run={run_id} --draft")
    parts.append(f"npm run build-clip-explorer -- --program={slug} --run={run_id}")
    # After a successful render, push artifacts up to Drive so other hosts
    # (and the share surface) can pick them up without re-rendering.
    parts.append(_publish_artifacts_subcommand(workspace, slug, run_id))
    chain = " && ".join(parts)
    log.info("videos.trigger_rerender: spawning for %s/%s (needs_hydrate=%s)", slug, run_id, needs_hydrate)
    log_handle = _open_render_log(slug, run_id)
    try:
        subprocess.Popen(  # noqa: S602
            ["sh", "-c", chain],
            cwd=str(_root()),
            stdout=log_handle if log_handle else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if log_handle else subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        if log_handle:
            log_handle.close()
        r.delete(_busy_key(slug, run_id), _started_key(slug, run_id))
        return False
    return True


_RENDER_FAILURE_AFTER_SECONDS = 8 * 60  # 8 min covers slowest renders + headroom


def render_status(slug: str, run_id: str) -> dict[str, Any]:
    """Report whether a render is in flight, succeeded, or appears failed.

    The Redis busy key has a 1-hour TTL and is set on every trigger but
    NEVER cleared on success (so polling apps can rate-limit re-renders).
    Treating that key alone as ground truth means the UI shows
    "rendering..." for an hour after a 60-second render.

    Two derived signals on top of the raw Redis flag:

    - **Success**: ``explorer/index.html`` (the final file both the full
      render chain and the build-only chain produce) has mtime newer
      than started_at. → busy=False.
    - **Failure**: Redis still busy, sentinel mtime not newer than
      started_at, AND it's been longer than the longest-plausible
      render. → busy=False but appears_failed=True so the UI can show
      "render failed, check /render-log" instead of spinning forever.

    Plain Redis-busy with neither signal yet (chain still in flight)
    returns busy=True, appears_failed=False.
    """
    r = _get_redis()
    busy_flag_set = bool(r.get(_busy_key(slug, run_id)))
    started = r.get(_started_key(slug, run_id))
    if isinstance(started, bytes):
        started = started.decode("utf-8")

    actually_done = False
    appears_failed = False
    if busy_flag_set and started:
        try:
            started_dt = dt.datetime.fromisoformat(started.replace("Z", "+00:00"))
            sentinel = explorer_dir(slug, run_id) / "index.html"
            if sentinel.exists():
                sentinel_mtime = dt.datetime.fromtimestamp(sentinel.stat().st_mtime, tz=dt.UTC)
                actually_done = sentinel_mtime > started_dt
            if not actually_done:
                age = (dt.datetime.now(dt.UTC) - started_dt).total_seconds()
                if age > _RENDER_FAILURE_AFTER_SECONDS:
                    appears_failed = True
        except (ValueError, OSError):
            pass

    busy = busy_flag_set and not actually_done and not appears_failed
    return {
        "program_slug": slug,
        "run_id": run_id,
        "busy": busy,
        "started_at": started,
        "appears_failed": appears_failed,
    }


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
