"""Public per-run summary payload.

Reads a focused subset of artifacts from the ACE Drive folder and composes
the JSON payload rendered by the public summary page (see
``docs/specs/2026-05-04-opp-summary-page-design.md``).

This is a separate, lighter loader than the full Workbench ``load_opp``.

**Drive layout** (as observed on labs, May 2026 — diverges from the
plugin's artifact-manifest.ts which reflects an older convention):

    ACE/<opp-slug>/
    ├── opp.yaml                         display_name (often == slug)
    ├── inputs/pdd.md                    Google Doc — hero name + description
    ├── connect-setup/
    │   ├── opportunity.md               markdown body, **Field:** value
    │   └── program.md                   markdown body
    ├── ocs-agent-config.md              opp-level (status only here)
    ├── ocs-setup/
    │   └── widget-handoff.md            markdown table with chatbot_public_id /
    │                                    chatbot_embed_key / chatbot_url
    ├── training-materials/
    │   ├── <Slides file>                application/vnd.google-apps.presentation
    │   ├── llo-manager-guide.md         Google Docs
    │   ├── flw-training-guide.md
    │   ├── quick-reference.md
    │   ├── faq.md
    │   └── onboarding-email-body.md
    └── runs/<run_id>/
        ├── run_state.yaml
        ├── open-questions.md            Google Doc — link only, not parsed
        └── 2-commcare/
            ├── pdd-to-learn-app_summary.md     frontmatter: title, nova_app_*
            ├── pdd-to-deliver-app_summary.md   frontmatter: title, nova_app_*
            └── app-deploy_summary.md            frontmatter: learn_app_url, deliver_app_url

Many fields are markdown body, not frontmatter — the loader uses targeted
regex extraction. Tolerant of missing/malformed files: every section is
independently nullable; a single failed read never 500s the page.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

import yaml

from apps.opps.drive_client import DriveClient, DriveFile

log = logging.getLogger(__name__)


# ─── Drive helpers ─────────────────────────────────────────────────


_FOLDER_MIME = "application/vnd.google-apps.folder"
_PRESENTATION_MIME = "application/vnd.google-apps.presentation"


def _is_folder(f: DriveFile) -> bool:
    return f.mime_type == _FOLDER_MIME


def _find(files: list[DriveFile], name: str) -> DriveFile | None:
    for f in files:
        if f.name == name:
            return f
    return None


def _find_folder(files: list[DriveFile], name: str) -> DriveFile | None:
    f = _find(files, name)
    return f if (f is not None and _is_folder(f)) else None


def _list(drive: DriveClient, folder_id: str) -> list[DriveFile]:
    try:
        return drive.list_files(folder_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: list %s failed: %s", folder_id, exc)
        return []


def _read_text(drive: DriveClient, f: DriveFile | None) -> str:
    if f is None:
        return ""
    try:
        content = drive.get_content(f.id, f.mime_type)
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: read %s failed: %s", f.name, exc)
        return ""
    return content.content or ""


# ─── Markdown / frontmatter parsing ────────────────────────────────


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(body: str) -> dict[str, Any]:
    if not body:
        return {}
    body = body.lstrip("﻿").lstrip()
    m = _FRONTMATTER_RE.match(body)
    if m is None:
        return {}
    try:
        data = yaml.safe_load(m.group(1)) or {}
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError as exc:
        log.warning("summary: malformed frontmatter: %s", exc)
        return {}


def _strip_frontmatter(body: str) -> str:
    if not body:
        return ""
    body = body.lstrip("﻿").lstrip()
    m = _FRONTMATTER_RE.match(body)
    return body[m.end():] if m else body


def _extract_field_line(body: str, label: str) -> str | None:
    """Extract the value from a ``**Label:** value`` line in markdown body.

    Tolerates both ``**Label:**`` (colon inside bold) and ``**Label**:``
    (colon outside bold), backtick-wrapped values, and trailing punctuation.
    Returns the value with leading/trailing whitespace and surrounding
    backticks stripped.
    """
    # Single regex: optional colon inside the bold pair, then mandatory
    # colon after. ``\*\*<label>:?\*\*\s*:?`` matches both forms.
    pat = re.compile(
        rf"\*\*\s*{re.escape(label)}\s*:?\s*\*\*\s*:?\s*(.+?)(?=\n|\*\*|$)",
        re.IGNORECASE,
    )
    m = pat.search(body)
    if m is None:
        return None
    raw = m.group(1).strip().rstrip(".,;:")
    raw = re.sub(r"^`+|`+$", "", raw).strip()
    return raw or None


def _extract_table_row(body: str, key: str) -> str | None:
    """Extract the value from a ``| `key` | `value` |`` markdown table row.

    Used by widget-handoff.md, where chatbot creds live in a table whose
    keys are themselves in backticks.
    """
    pat = re.compile(
        rf"\|\s*`?{re.escape(key)}`?\s*\|\s*([^|]+?)\s*\|",
        re.IGNORECASE,
    )
    m = pat.search(body)
    if m is None:
        return None
    raw = m.group(1).strip()
    raw = re.sub(r"^`+|`+$", "", raw).strip()
    return raw or None


# ─── Hero name + description from inputs/pdd.md ────────────────────


_DOCS_COMMENT_MARKER_RE = re.compile(r"\[[a-z]\](\[[a-z]\])*", re.IGNORECASE)


def _extract_hero_name(pdd_body: str) -> str | None:
    """Pull a friendly title from the PDD's opening line.

    The plugin's PDDs typically open with::

        Intervention Design Document: <Friendly Name>

    or::

        # <Friendly Name>

    In both cases the friendly name follows the first colon (or the H1).
    Returns ``None`` if no plausible title is found — caller falls back
    to ``opp.yaml`` ``display_name`` then to the slug.
    """
    if not pdd_body:
        return None
    for line in _strip_frontmatter(pdd_body).splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("# "):
            candidate = line[2:].strip()
            if candidate:
                return _DOCS_COMMENT_MARKER_RE.sub("", candidate).strip()
        if ":" in line:
            label, _, rest = line.partition(":")
            if label.lower().strip() in {
                "intervention design document",
                "program design document",
                "title",
            }:
                candidate = rest.strip()
                if candidate:
                    return _DOCS_COMMENT_MARKER_RE.sub("", candidate).strip()
        # If the very first non-blank line is just plain text (no colon,
        # no heading), use it — it's almost always the doc title.
        return _DOCS_COMMENT_MARKER_RE.sub("", line).strip() or None
    return None


def _extract_hero_description(pdd_body: str) -> str:
    """Pull a clean one-paragraph description from the PDD.

    Strategy: find a heading-like line of "Overview" / "Summary" /
    "Background" (case-insensitive, not nested under a section), and
    return the first non-empty paragraph that follows. Falls back to
    the second paragraph of the document if no such heading exists.

    Strips Google Docs comment markers (``[a][b]``) and surrounding
    asterisks.
    """
    if not pdd_body:
        return ""
    text = _strip_frontmatter(pdd_body)
    lines = text.splitlines()

    overview_idx = None
    for i, line in enumerate(lines):
        s = line.strip()
        low = s.lower().lstrip("# ").rstrip(":").strip()
        if low in {"overview", "summary", "abstract"}:
            overview_idx = i
            break

    start = overview_idx + 1 if overview_idx is not None else 0
    paragraph_lines: list[str] = []
    seen_blank_after_heading = overview_idx is None  # if no heading, take 2nd para

    for line in lines[start:]:
        s = line.strip()
        if not s:
            if paragraph_lines:
                break
            continue
        if s.startswith("#"):
            if paragraph_lines:
                break
            continue
        # Skip the document's own H1 / first prose line if no heading was
        # found — we want the SECOND paragraph (first paragraph is often
        # boilerplate / metadata).
        if overview_idx is None and not seen_blank_after_heading:
            seen_blank_after_heading = True
            continue
        paragraph_lines.append(s)

    desc = " ".join(paragraph_lines)
    desc = _DOCS_COMMENT_MARKER_RE.sub("", desc)
    # Strip Markdown bold/italic wrappers but keep their content.
    desc = re.sub(r"\*\*(.+?)\*\*", r"\1", desc)
    desc = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", desc)
    return desc.strip()


# ─── Apps section ──────────────────────────────────────────────────


def _read_apps(
    drive: DriveClient, run_children: list[DriveFile]
) -> list[dict]:
    """Build the apps[] payload from runs/<id>/2-commcare/."""
    phase2 = _find_folder(run_children, "2-commcare")
    if phase2 is None:
        return []
    p2_children = _list(drive, phase2.id)

    deploy = _find(p2_children, "app-deploy_summary.md")
    deploy_fm = _parse_frontmatter(_read_text(drive, deploy))

    out: list[dict] = []
    for kind, summary_filename, hq_url_key in (
        ("Learn", "pdd-to-learn-app_summary.md", "learn_app_url"),
        ("Deliver", "pdd-to-deliver-app_summary.md", "deliver_app_url"),
    ):
        f = _find(p2_children, summary_filename)
        if f is None:
            continue
        fm = _parse_frontmatter(_read_text(drive, f))
        name = fm.get("title") or fm.get("display_name") or fm.get("name") or f"{kind} app"
        out.append({
            "kind": kind,
            "name": str(name),
            "nova_url": fm.get("nova_app_url"),
            "hq_url": deploy_fm.get(hq_url_key),
        })
    return out


# ─── Connect section ───────────────────────────────────────────────


def _read_connect(
    drive: DriveClient, opp_children: list[DriveFile]
) -> tuple[dict | None, str | None]:
    """Return (connect_payload, opp_end_date_iso).

    The end_date is also returned because the hero status derivation
    needs it.
    """
    folder = _find_folder(opp_children, "connect-setup")
    if folder is None:
        return None, None
    children = _list(drive, folder.id)

    opp_md = _find(children, "opportunity.md")
    prog_md = _find(children, "program.md")

    opp_block: dict | None = None
    end_date: str | None = None
    if opp_md is not None:
        body = _read_text(drive, opp_md)
        url = _extract_field_line(body, "URL")
        name = _extract_field_line(body, "Name")
        opp_uuid = _extract_field_line(body, "Opportunity ID (UUID)")
        # Dates appear in a markdown table — `start_date` / `end_date` are
        # column-cell values. Fall back to bullet lookup just in case.
        start_date = (
            _extract_table_value(body, "start_date")
            or _extract_field_line(body, "start_date")
        )
        end_date = (
            _extract_table_value(body, "end_date")
            or _extract_field_line(body, "end_date")
        )
        if name or url or opp_uuid:
            opp_block = {
                "name": name or "Connect opportunity",
                "url": url,
                "start_date": start_date,
                "end_date": end_date,
            }

    prog_block: dict | None = None
    if prog_md is not None:
        body = _read_text(drive, prog_md)
        prog_url = _extract_field_line(body, "URL")
        prog_name = _extract_field_line(body, "Name")
        prog_uuid = _extract_field_line(body, "Program ID (UUID)")
        # Older runs' program.md doesn't carry an explicit URL — construct
        # it from the program UUID + the org slug we can pull out of the
        # opportunity URL (e.g. .../a/<org_slug>/opportunity/<id>/).
        if prog_url is None and prog_uuid and opp_block and opp_block.get("url"):
            prog_url = _construct_program_url(opp_block["url"], prog_uuid)
        if prog_name or prog_url or prog_uuid:
            prog_block = {
                "name": prog_name or "Program",
                "url": prog_url,
            }

    if opp_block or prog_block:
        return {"opportunity": opp_block, "program": prog_block}, end_date
    return None, None


def _construct_program_url(opp_url: str, program_uuid: str) -> str | None:
    """Derive a working program link from the opportunity URL.

    Connect mounts the program app at ``/a/<org_slug>/program/`` (the
    program-list home). The per-program detail URL ``/program/<uuid>/view``
    *exists* in upstream commcare-connect's program/urls.py (it points
    at ``ManagedOpportunityList``) but renders an error page when hit
    directly — the view's template assumes a wrapper context that the
    standalone URL can't provide. The PM-side program management UI
    only exposes the program via HTMX modals on the home page, never
    as a top-level navigable URL.

    So we link to the program-list home and let the viewer find the
    program in context. ``program_uuid`` is unused but kept in the
    signature so callers don't change shape if a real per-program URL
    appears in the future.
    """
    del program_uuid  # see docstring
    m = re.search(r"^(https?://[^/]+/a/[^/]+)/", opp_url)
    if m is None:
        return None
    return f"{m.group(1)}/program/"


def _extract_table_value(body: str, key: str) -> str | None:
    """Pull a value from a ``| key | value |`` row, with `key` un-quoted
    (no backticks). Used for ``start_date`` / ``end_date`` columns in
    the opportunity.md core-config table.
    """
    pat = re.compile(
        rf"\|\s*`?{re.escape(key)}`?\s*\|\s*([^|]+?)\s*\|",
        re.IGNORECASE,
    )
    m = pat.search(body)
    if m is None:
        return None
    raw = m.group(1).strip()
    # Strip parentheticals like "2026-06-14 (placeholder — LLO sets...)".
    raw = re.split(r"\s+\(", raw, maxsplit=1)[0].strip()
    raw = re.sub(r"^`+|`+$", "", raw).strip()
    return raw or None


# ─── Training section ──────────────────────────────────────────────


_TRAINING_DOC_TITLES = {
    "llo-manager-guide.md":     "LLO manager guide",
    "flw-training-guide.md":    "FLW training guide",
    "quick-reference.md":       "Quick reference card",
    "faq.md":                   "FAQ",
    "onboarding-email-body.md": "Onboarding email",
    # ``training-deck-outline.md`` is an intermediate artifact (input to
    # the deck builder), not a public deliverable — deliberately omitted.
}


def _read_training(
    drive: DriveClient, opp_children: list[DriveFile]
) -> dict | None:
    folder = _find_folder(opp_children, "training-materials")
    if folder is None:
        return None
    children = _list(drive, folder.id)

    deck_block: dict | None = None
    docs: list[dict] = []
    for f in children:
        if _is_folder(f):
            continue
        if f.mime_type == _PRESENTATION_MIME and deck_block is None:
            deck_block = {
                "title": f.name,
                "url": f.web_view_link,
            }
            continue
        title = _TRAINING_DOC_TITLES.get(f.name)
        if title is None:
            continue
        docs.append({"title": title, "url": f.web_view_link})

    order = list(_TRAINING_DOC_TITLES.values())
    docs.sort(key=lambda d: order.index(d["title"]) if d["title"] in order else 99)

    if deck_block is None and not docs:
        return None
    return {"deck": deck_block, "docs": docs}


# ─── Assistant (OCS) section ───────────────────────────────────────


def _read_assistant(
    drive: DriveClient, opp_children: list[DriveFile]
) -> dict | None:
    folder = _find_folder(opp_children, "ocs-setup")
    if folder is None:
        return None
    children = _list(drive, folder.id)
    handoff = _find(children, "widget-handoff.md")
    if handoff is None:
        return None
    body = _read_text(drive, handoff)
    public_id = _extract_table_row(body, "chatbot_public_id")
    embed_key = _extract_table_row(body, "chatbot_embed_key")
    chatbot_url = _extract_table_row(body, "chatbot_url")
    if not public_id or not embed_key:
        return None
    return {
        "ocs_url": chatbot_url,
        "public_id": public_id,
        "embed_key": embed_key,
    }


# ─── Open questions (run folder) ───────────────────────────────────


def _read_open_questions(
    drive: DriveClient, run_children: list[DriveFile]
) -> dict | None:
    f = _find(run_children, "open-questions.md")
    if f is None or not f.web_view_link:
        return None
    return {"url": f.web_view_link}


# ─── Status ─────────────────────────────────────────────────────────


def _resolve_status(
    drive: DriveClient,
    run_children: list[DriveFile],
    end_date_iso: str | None,
) -> str:
    """Return ``closed`` if a closeout cycle-grade is present, otherwise
    ``active`` / ``in_progress`` based on the connect end_date.

    Looks for cycle-grade.md in any of:
        runs/<id>/closeout/cycle-grade.md
        runs/<id>/6-llo/cycle-grade.md     (legacy candidate)
        runs/<id>/7-closeout/cycle-grade.md
        runs/<id>/<phase-numbered-folder>/cycle-grade.md
    """
    for child in run_children:
        if not _is_folder(child):
            continue
        if not (child.name == "closeout" or re.match(r"^\d+-", child.name)):
            continue
        try:
            inner = _list(drive, child.id)
        except Exception:  # noqa: BLE001
            inner = []
        if any(f.name == "cycle-grade.md" for f in inner):
            return "closed"

    if end_date_iso and _is_future(end_date_iso):
        return "active"
    return "in_progress"


def _is_future(date_iso: str) -> bool:
    try:
        d = date.fromisoformat(str(date_iso)[:10])
    except (TypeError, ValueError):
        return False
    return d >= date.today()


# ─── Top-level entry point ─────────────────────────────────────────


def build_summary_payload(
    drive: DriveClient,
    *,
    workspace,
    opp_slug: str,
    run_id: str,
) -> dict | None:
    """Build the public summary JSON payload for a per-run summary page.

    Returns ``None`` when the workspace's ACE root, the opp folder, or
    the requested run folder can't be located. Callers map ``None`` to
    a 404 so the API doesn't leak which segment was the miss.
    """
    ace_root_id = getattr(workspace, "drive_root_folder_id", None)
    if not ace_root_id:
        return None

    ace_children = _list(drive, ace_root_id)
    opp_folder = _find_folder(ace_children, opp_slug)
    if opp_folder is None:
        return None

    opp_children = _list(drive, opp_folder.id)

    runs_folder = _find_folder(opp_children, "runs")
    if runs_folder is None:
        return None
    run_dirs = _list(drive, runs_folder.id)
    run_folder = _find_folder(run_dirs, run_id)
    if run_folder is None:
        return None
    run_children = _list(drive, run_folder.id)

    # ── Hero (display_name + description) ──
    inputs_folder = _find_folder(opp_children, "inputs")
    pdd_body = ""
    if inputs_folder is not None:
        pdd_md = _find(_list(drive, inputs_folder.id), "pdd.md")
        pdd_body = _read_text(drive, pdd_md)

    hero_name = _extract_hero_name(pdd_body)
    description = _extract_hero_description(pdd_body)

    opp_yaml = _find(opp_children, "opp.yaml")
    opp_meta: dict = {}
    if opp_yaml is not None:
        try:
            opp_meta = yaml.safe_load(_read_text(drive, opp_yaml)) or {}
        except yaml.YAMLError:
            opp_meta = {}
    yaml_display = opp_meta.get("display_name")
    # Prefer the PDD-derived friendly name, but only if it differs from
    # the slug (some PDDs lead with a generic boilerplate header).
    if hero_name and hero_name.lower() != opp_slug.lower():
        display_name = hero_name
    elif yaml_display and yaml_display != opp_slug:
        display_name = yaml_display
    else:
        display_name = hero_name or yaml_display or opp_slug

    # ── Connect ──
    connect_section, end_date_iso = _read_connect(drive, opp_children)

    # ── Status ──
    status = _resolve_status(drive, run_children, end_date_iso)

    # ── Sections ──
    apps = _read_apps(drive, run_children)
    training = _read_training(drive, opp_children)
    assistant = _read_assistant(drive, opp_children)
    open_questions = _read_open_questions(drive, run_children)

    workspace_slug = getattr(workspace, "slug", "")
    workbench_url = (
        f"/w/{workspace_slug}/opps/{opp_slug}/runs/{run_id}"
        if workspace_slug
        else None
    )

    return {
        "opp": {
            "workspace_slug": workspace_slug,
            "slug": opp_slug,
            "run_id": run_id,
            "display_name": display_name,
            "description": description,
            "status": status,
            "end_date": end_date_iso,
        },
        "apps": apps,
        "connect": connect_section,
        "training": training,
        "assistant": assistant,
        "open_questions": open_questions,
        "workbench_url": workbench_url,
    }
