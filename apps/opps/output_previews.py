"""Previews of a run's outputs — screenshots of the Learn app, a labs dashboard.

A preview belongs to the OUTPUT and lives with the phase that built it, whoever
took it (docs/specs/2026-09-29-output-previews-design.md)::

    <run>/<N>-<phase>/previews/<output-slug>/_previews.yaml
    <run>/<N>-<phase>/previews/<output-slug>/<NN>-<step>.png

Phase 6 walks the apps on the emulator but writes the frames into Phase 3's
folder, because Phase 3 is where a reader meets the apps. The index names the
output (``phase`` + ``output_key``, the dotted key under
``phases.<phase>.products``), who took the frames (``captured_by`` — the replay
reveals them at that skill's beat, not at the output's), and the frames in
display order.

Two older shapes are still read, so runs already in Drive get pictures too:

* a previews folder with images and no index (shown in name order);
* no previews folder at all — Phase 6's own capture manifest
  (``6-qa-and-training/app-screenshot-capture_manifest.yaml``), whose frames are
  matched to the Learn / Deliver app by the manifest's own ``journeys[].app``,
  else by the journey's name (``journey-learn-*``) — a guess from a naming
  convention. Only used for an app nothing better covers.

**The run folder is the boundary.** A frame is kept only if its file id is in
the run's own tree: an index is agent-written, and the viewer serves any
preview id it is handed, so an id from outside the run would otherwise be a way
to read any file the service account can see.

Two halves: :func:`load_output_previews` does the Drive reads at snapshot-load
time (reusing the recursive listing the loader has just made — it is cached);
:func:`attach_previews` is pure, and runs at serialize time against the
products catalogue.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import yaml

from apps.opps.drive_client import DriveClient, DriveFile

log = logging.getLogger(__name__)

INDEX_NAMES = ("_previews.yaml", "_previews.yml")

#: Phase 6's capture manifest — the legacy source of app screenshots.
LEGACY_CAPTURE_MANIFEST = "app-screenshot-capture_manifest.yaml"
LEGACY_CAPTURED_BY = "app-screenshot-capture"
LEGACY_CAPTURED_PHASE = "qa-and-training"

_PREVIEW_PATH = re.compile(
    r"^(?P<phase_folder>\d+-[^/]+)/previews/(?P<slug>[^/]+)/(?P<name>[^/]+)$"
)
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_CAPTION_MAX = 300
_FOLDER_MIME = "application/vnd.google-apps.folder"


def output_slug(key: str) -> str:
    """``apps.learn`` → ``apps-learn`` — an output key as a folder name."""
    return re.sub(r"[^a-z0-9]+", "-", str(key or "").lower()).strip("-")


# --------------------------------------------------------------------------- #
# load (Drive)
# --------------------------------------------------------------------------- #
def load_output_previews(
    client: DriveClient,
    run_folder_id: str,
    *,
    lineage_folder_ids: tuple[str, ...] = (),
) -> list[dict]:
    """Every preview record in one run, from Drive. Never raises.

    Each record::

        {source, phase, output_key, slug, app, captured_by, captured_phase,
         captured_at, items: [{file_id, name, caption, mime_type}]}

    ``source`` is ``index`` | ``folder`` | ``legacy``; ``app`` (``learn`` /
    ``deliver``) is set only on legacy records.
    """
    try:
        tree = client.list_files(run_folder_id, recursive=True)
    except Exception:  # noqa: BLE001 — previews are a nicety, never a failure
        log.warning("output_previews: run tree listing failed", exc_info=True)
        return []
    by_id = {f.id: f for f in tree if f.mime_type != _FOLDER_MIME}
    # A FORK's screenshots may live in the run it was forked from: the forker
    # does not copy a phase's screenshots/ (ace-web#758) while the manifest it
    # copies still names them. Those runs are the same opp, so their files may
    # be shown — but only frames are looked up there; previews folders and
    # manifests are this run's own.
    shown_ids = dict(by_id)
    for folder_id in lineage_folder_ids:
        try:
            for f in client.list_files(folder_id, recursive=True):
                if f.mime_type != _FOLDER_MIME:
                    shown_ids.setdefault(f.id, f)
        except Exception:  # noqa: BLE001
            log.warning("output_previews: fork source listing failed", exc_info=True)

    records: list[dict] = []
    folders: dict[tuple[str, str], list[DriveFile]] = {}
    for f in by_id.values():
        m = _PREVIEW_PATH.match(f.path or "")
        if m:
            folders.setdefault((m["phase_folder"], m["slug"]), []).append(f)

    for (_phase_folder, slug), files in sorted(folders.items()):
        index = next((f for f in files if f.name in INDEX_NAMES), None)
        record = _read_index(client, index, shown_ids) if index else None
        if record is None:
            record = _folder_record(slug, files)
        # An index with no items is kept: it is the writer saying "nothing to
        # show" (a leg that did not pass), and it must stop the legacy
        # fallback from showing that leg's frames. An index-less folder with
        # no images says nothing and is dropped.
        if record is not None and (record["items"] or record["source"] == "index"):
            record["slug"] = slug
            records.append(record)

    manifest = next(
        (
            f
            for f in by_id.values()
            if f.name == LEGACY_CAPTURE_MANIFEST and "/previews/" not in (f.path or "")
        ),
        None,
    )
    if manifest is not None:
        records.extend(_read_legacy_manifest(client, manifest, shown_ids))
    return records


def _read_index(client: DriveClient, index: DriveFile, by_id: dict[str, DriveFile]) -> dict | None:
    data = _read_yaml(client, index)
    if not isinstance(data, dict):
        return None
    items = []
    for raw in data.get("items") or []:
        if not isinstance(raw, dict):
            continue
        item = _item(by_id, raw.get("file_id"), raw.get("name"), raw.get("caption"))
        if item is not None:
            items.append(item)
    return {
        "source": "index",
        "phase": _str(data.get("phase")),
        "output_key": _str(data.get("output_key")),
        "app": None,
        "captured_by": _str(data.get("captured_by")),
        "captured_phase": _str(data.get("captured_phase")),
        "captured_at": _str(data.get("captured_at")),
        "items": items,
    }


def _folder_record(slug: str, files: list[DriveFile]) -> dict:
    images = sorted(
        (f for f in files if _is_image(f)),
        key=lambda f: f.name,
    )
    return {
        "source": "folder",
        "phase": None,
        "output_key": None,
        "app": None,
        "captured_by": None,
        "captured_phase": None,
        "captured_at": None,
        "items": [_meta(f, None) for f in images],
    }


def _read_legacy_manifest(
    client: DriveClient, manifest: DriveFile, by_id: dict[str, DriveFile]
) -> list[dict]:
    """Phase 6's capture manifest → one record per app it has frames of.

    Reads every container the plugin's own reader accepts
    (``lib/capture-manifest.ts::collectCaptureEntries``): a flat ``captures[]``,
    ``journeys[].{steps,screenshots}[]``, and a top-level ``screenshots[]``;
    ``step`` or ``step_name``. Frames marked ``duplicate_of`` are skipped —
    they are the same moment captured twice.
    """
    data = _read_yaml(client, manifest)
    if not isinstance(data, dict):
        return []

    # The journey block names its app outright on most manifests
    # (``journeys[].app``), under both its id and its recipe base — rows cite
    # either (``journey_id: journey-learn-pass`` / ``journey: journey-learn``).
    app_by_journey: dict[str, str] = {}
    failed: set[str] = set()
    for journey in data.get("journeys") or []:
        if not isinstance(journey, dict):
            continue
        # Screenshots only ever come from a passing journey (the plugin's
        # hard rule); a leg the manifest records as not passing shows nothing.
        status = str(journey.get("status") or "").lower()
        if status and status != "pass":
            for ref in (journey.get("journey_id"), journey.get("id"), journey.get("recipe_base")):
                if ref:
                    failed.add(str(ref))
        app = str(journey.get("app") or "").lower()
        if app in {"learn", "deliver"}:
            for ref in (journey.get("journey_id"), journey.get("id"), journey.get("recipe_base")):
                if ref:
                    app_by_journey[str(ref)] = app

    rows: list[tuple[str, dict]] = []  # (journey ref, row)
    for row in data.get("captures") or []:
        if isinstance(row, dict):
            rows.append((_journey_ref(row), row))
    for journey in data.get("journeys") or []:
        if not isinstance(journey, dict):
            continue
        jid = str(journey.get("journey_id") or journey.get("id") or "")
        for container in ("steps", "screenshots"):
            for row in journey.get(container) or []:
                if isinstance(row, dict):
                    rows.append((_journey_ref(row) or jid, row))
    for row in data.get("screenshots") or []:
        if isinstance(row, dict):
            rows.append((_journey_ref(row), row))

    by_app: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for jid, row in rows:
        if row.get("duplicate_of") or jid in failed:
            continue
        app = app_by_journey.get(jid) or _legacy_app(jid, str(row.get("drive_path") or ""))
        if app is None:
            continue
        item = _item(by_id, row.get("file_id"), None, row.get("shows"))
        if item is None or item["file_id"] in seen:
            continue
        seen.add(item["file_id"])
        by_app.setdefault(app, []).append(item)

    return [
        {
            "source": "legacy",
            "phase": None,
            "output_key": None,
            "slug": None,
            "app": app,
            "captured_by": LEGACY_CAPTURED_BY,
            "captured_phase": LEGACY_CAPTURED_PHASE,
            "captured_at": None,
            "items": items,
        }
        for app, items in by_app.items()
    ]


def _journey_ref(row: dict) -> str:
    return str(row.get("journey_id") or row.get("journey") or "")


def _legacy_app(journey_id: str, drive_path: str) -> str | None:
    """Learn or Deliver from the journey's name, when the manifest doesn't say."""
    text = f"{journey_id} {drive_path}".lower()
    has_learn, has_deliver = "learn" in text, "deliver" in text
    if has_learn and not has_deliver:
        return "learn"
    if has_deliver and not has_learn:
        return "deliver"
    return None


def _item(
    by_id: dict[str, DriveFile], file_id: Any, name: Any, caption: Any
) -> dict | None:
    f = by_id.get(str(file_id or ""))
    if f is None or not _is_image(f):
        return None
    return _meta(f, caption, name)


def _meta(f: DriveFile, caption: Any, name: Any = None) -> dict:
    text = _str(caption)
    if text and len(text) > _CAPTION_MAX:
        text = text[: _CAPTION_MAX - 1].rstrip() + "…"
    return {
        "file_id": f.id,
        "name": _str(name) or f.name,
        "caption": text,
        "mime_type": f.mime_type or "image/png",
    }


def _plain_caption(text: str | None) -> str | None:
    """A caption as plain text. The plugin writes ``shows:`` lines in markdown
    (``the **In Progress** section``), and a thumbnail caption is not a place
    to render markdown — shown raw, the asterisks read as noise."""
    if not text:
        return text
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip() or None


def _is_image(f: DriveFile) -> bool:
    return (f.mime_type or "").startswith("image/") or f.name.lower().endswith(_IMAGE_SUFFIXES)


def _read_yaml(client: DriveClient, f: DriveFile) -> Any:
    try:
        text = client.get_content(f.id, f.mime_type).content
    except Exception:  # noqa: BLE001
        log.warning("output_previews: could not read %s", f.path or f.name, exc_info=True)
        return None
    # A YAML file written as a Google Doc comes back with every newline as
    # \r\n\r\n\r\n (skills/_training-template.md in the plugin). Blank lines
    # between mapping rows are harmless to YAML; carriage returns are not.
    text = text.replace("\r\n\r\n\r\n", "\n").replace("\r\n", "\n")
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        log.warning("output_previews: %s is not valid YAML", f.path or f.name)
        return None


# --------------------------------------------------------------------------- #
# attach (pure)
# --------------------------------------------------------------------------- #
def attach_previews(products: list[dict], records: list[dict]) -> list[dict]:
    """Give each product a ``previews`` list, from the records that name it.

    Each preview: ``{file_id, name, caption, mime_type, captured_by,
    captured_phase}``.

    Match order: an index record by ``phase`` + ``output_key`` (the key the
    product was listed under, or one it absorbed when de-duplicated); any
    current-layout record by folder slug; then — only for an app no current
    record covered, even with an EMPTY index (the writer's "nothing to show")
    — the legacy Phase 6 manifest by app. A record feeds one product at most.
    """
    out = [{**p, "previews": []} for p in products]
    used: set[int] = set()

    def keys(p: dict) -> list[str]:
        return [str(p.get("key") or ""), *[str(a) for a in p.get("aliases") or []]]

    covered: set[str] = set()  # product ids a current-layout record answered

    def give(p: dict, i: int, rec: dict) -> None:
        used.add(i)
        covered.add(str(p.get("id")))
        # Captions are cleaned here, at serialize time, not when read: the
        # snapshot cache holds what was read, so a reader-side fix would not
        # reach a cached run until its Drive files next changed.
        p["previews"].extend(
            {
                **item,
                "caption": _plain_caption(item.get("caption")),
                "captured_by": rec.get("captured_by"),
                "captured_phase": rec.get("captured_phase"),
            }
            for item in rec["items"]
        )

    for i, rec in enumerate(records):
        if rec["source"] != "index" or not rec.get("output_key"):
            continue
        for p in out:
            same_phase = not rec.get("phase") or rec["phase"] == p.get("phase")
            if same_phase and rec["output_key"] in keys(p):
                give(p, i, rec)
                break

    for i, rec in enumerate(records):
        if i in used or rec["source"] == "legacy" or not rec.get("slug"):
            continue
        for p in out:
            if rec["slug"] in {output_slug(k) for k in keys(p)}:
                give(p, i, rec)
                break

    for i, rec in enumerate(records):
        if rec["source"] != "legacy" or not rec["items"]:
            continue
        for p in out:
            if p.get("kind") != "commcare_app" or _app_of(p) != rec["app"]:
                continue
            if str(p.get("id")) in covered and not _only_fallback(p):
                continue
            # Phase 6's walk of the real app beats the capture skill's HQ
            # form-summary fallback — the fallback exists for an app nothing
            # photographed, and a fork's walk frames sit in its source run.
            p["previews"] = [
                pv for pv in p["previews"] if pv.get("captured_by") != FALLBACK_CAPTURER
            ]
            give(p, i, rec)
            break
    return out


#: The utility that photographs whatever has no picture. For an app its frame
#: is the HQ form summary — a fallback, never preferred over the emulator walk.
FALLBACK_CAPTURER = "output-preview-capture"


def _only_fallback(product: dict) -> bool:
    previews = product.get("previews") or []
    return bool(previews) and all(pv.get("captured_by") == FALLBACK_CAPTURER for pv in previews)


def _app_of(product: dict) -> str | None:
    names = [n for n in str(product.get("key") or "").lower().split(".") if not n.isdigit()]
    last = names[-1] if names else ""
    for app in ("learn", "deliver"):
        if last.startswith(app):
            return app
    return None


def _str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is not None and not isinstance(value, (dict, list, bool)):
        return str(value)
    return None
