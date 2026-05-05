"""Public per-run summary payload.

Reads a focused subset of artifacts under ``ACE/<opp>/runs/<run_id>/`` and
composes the JSON payload rendered by the public summary page (see
``docs/specs/2026-05-04-opp-summary-page-design.md``).

This is intentionally a separate, lighter loader than the full Workbench
``load_opp`` — public traffic shouldn't pay the cost of judge verdicts,
gate history, scorecards, etc. We only read what the summary page renders.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

import yaml
from django.conf import settings

from apps.opps.drive_client import DriveClient, DriveFile

log = logging.getLogger(__name__)


# --- Drive helpers (small + local; deliberately not imported from sync.py
#     to avoid coupling this lightweight loader to the full Workbench loader). ---


_FOLDER_MIME = "application/vnd.google-apps.folder"


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


def _read_text(drive: DriveClient, f: DriveFile) -> str:
    try:
        content = drive.get_content(f.id, f.mime_type)
    except Exception as exc:  # noqa: BLE001 — Drive errors degrade silently
        log.warning("summary: failed to read %s: %s", f.name, exc)
        return ""
    return content.content or ""


# --- Markdown / frontmatter parsing ---


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(body: str) -> dict[str, Any]:
    """Return the YAML frontmatter at the top of a markdown file, or {}.

    Tolerant of trailing whitespace, BOM, and missing/malformed frontmatter
    — we never let a parse error 500 the public page.
    """
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


def _first_paragraph(body: str) -> str:
    """Return the first non-heading, non-blank paragraph from a markdown body.

    Used for the hero description: the first prose sentence/paragraph after
    the H1 of the PDD.
    """
    text = _strip_frontmatter(body)
    paragraphs: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        s = line.rstrip()
        if not s.strip():
            if buf:
                paragraphs.append(" ".join(buf).strip())
                buf = []
            continue
        if s.lstrip().startswith("#"):
            if buf:
                paragraphs.append(" ".join(buf).strip())
                buf = []
            continue
        if s.lstrip().startswith(">"):
            # blockquotes (e.g. "> Open questions:") aren't the description
            continue
        buf.append(s.strip())
    if buf:
        paragraphs.append(" ".join(buf).strip())
    return paragraphs[0] if paragraphs else ""


# --- Per-section extractors ---


def _connect_opp_url(opportunity_id: str | None) -> str | None:
    if not opportunity_id:
        return None
    base = getattr(settings, "ACE_CONNECT_BASE_URL", "https://connect.dimagi.com").rstrip("/")
    return f"{base}/o/opportunities/{opportunity_id}/"


def _connect_program_url(program_id: str | None) -> str | None:
    if not program_id:
        return None
    base = getattr(settings, "ACE_CONNECT_BASE_URL", "https://connect.dimagi.com").rstrip("/")
    return f"{base}/o/programs/{program_id}/"


_HQ_BUILD_URL_RE = re.compile(
    r"https?://[^\s)]+commcarehq\.org/[^\s)]*"
)


def _extract_hq_url(deployment_summary: str, kind: str) -> str | None:
    """Best-effort extraction of the HQ build URL for a given app kind.

    The deployment-summary.md format is markdown the plugin writes; it's
    stable but not contractually structured, so we walk it line-by-line
    looking for the first HQ URL inside the section that mentions the
    kind ("learn" or "deliver"), case-insensitive.
    """
    kind_l = kind.lower()
    in_section = False
    for line in deployment_summary.splitlines():
        low = line.lower()
        if low.lstrip().startswith("#"):
            in_section = kind_l in low
            continue
        if in_section:
            m = _HQ_BUILD_URL_RE.search(line)
            if m:
                return m.group(0)
    # Fallback: any HQ URL in the doc
    m = _HQ_BUILD_URL_RE.search(deployment_summary)
    return m.group(0) if m else None


_TRAINING_DOC_TITLES = {
    "llo-manager-guide.md":   "LLO manager guide",
    "flw-training-guide.md":  "FLW training guide",
    "quick-reference.md":     "Quick reference card",
    "faq.md":                 "FAQ",
    "onboarding-email-body.md": "Onboarding email",
}


def _ocs_standalone_url(public_id: str | None, widget_handoff_fm: dict) -> str | None:
    """Resolve the OCS standalone chatbot URL.

    Prefers ``widget_url`` from ``ocs-setup/widget-handoff.md`` frontmatter.
    Falls back to a constructed URL from ``public_id`` against
    ``ACE_OCS_PUBLIC_BASE`` (default ``https://chatbots.dimagi.com``).
    The exact path component is to be confirmed against a live OCS
    instance during smoke testing — for now we use the embed
    ``/c/<public_id>/`` shape which matches the widget's anonymous
    chat endpoint.
    """
    widget_url = widget_handoff_fm.get("widget_url")
    if isinstance(widget_url, str) and widget_url.strip():
        return widget_url.strip()
    if not public_id:
        return None
    base = getattr(settings, "ACE_OCS_PUBLIC_BASE", "https://chatbots.dimagi.com").rstrip("/")
    return f"{base}/c/{public_id}/"


# --- Top-level entry point ---


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

    The ``workspace`` arg is duck-typed: we only read
    ``drive_root_folder_id`` and ``slug`` off it.
    """
    ace_root_id = getattr(workspace, "drive_root_folder_id", None)
    if not ace_root_id:
        return None

    # ── Locate the opp folder ──
    try:
        ace_children = drive.list_files(ace_root_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: list ACE root failed: %s", exc)
        return None
    opp_folder = _find_folder(ace_children, opp_slug)
    if opp_folder is None:
        return None

    try:
        opp_children = drive.list_files(opp_folder.id)
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: list opp folder failed: %s", exc)
        return None

    # ── Locate the requested run folder ──
    runs_folder = _find_folder(opp_children, "runs")
    if runs_folder is None:
        return None
    try:
        run_dirs = drive.list_files(runs_folder.id)
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: list runs failed: %s", exc)
        return None
    run_folder = _find_folder(run_dirs, run_id)
    if run_folder is None:
        return None
    try:
        run_children = drive.list_files(run_folder.id)
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: list run folder failed: %s", exc)
        return None

    # ── Hero ──
    opp_yaml = _find(opp_children, "opp.yaml")
    opp_meta: dict = {}
    if opp_yaml is not None:
        try:
            opp_meta = yaml.safe_load(_read_text(drive, opp_yaml)) or {}
        except yaml.YAMLError:
            opp_meta = {}
    display_name = opp_meta.get("display_name") or opp_slug

    pdd_file = _find(run_children, "pdd.md")
    description = ""
    if pdd_file is not None:
        description = _first_paragraph(_read_text(drive, pdd_file))

    # ── Connect ──
    connect_section: dict | None = None
    connect_folder = _find_folder(run_children, "connect-setup")
    end_date_iso: str | None = None
    if connect_folder is not None:
        try:
            connect_children = drive.list_files(connect_folder.id)
        except Exception as exc:  # noqa: BLE001
            log.warning("summary: list connect-setup failed: %s", exc)
            connect_children = []

        opp_md = _find(connect_children, "opportunity.md")
        prog_md = _find(connect_children, "program.md")
        opp_fm = _parse_frontmatter(_read_text(drive, opp_md)) if opp_md else {}
        prog_fm = _parse_frontmatter(_read_text(drive, prog_md)) if prog_md else {}

        opportunity_id = opp_fm.get("opportunity_id")
        program_id = prog_fm.get("program_id") or opp_fm.get("program_id")
        end_date_iso = opp_fm.get("end_date")

        opp_url = _connect_opp_url(opportunity_id)
        prog_url = _connect_program_url(program_id)

        opp_block = None
        if opp_md is not None and (opp_fm.get("name") or opportunity_id):
            opp_block = {
                "name": opp_fm.get("name") or display_name,
                "url": opp_url,
                "start_date": opp_fm.get("start_date"),
                "end_date": end_date_iso,
            }
        prog_block = None
        if prog_md is not None and (prog_fm.get("name") or program_id):
            prog_block = {
                "name": prog_fm.get("name") or "Program",
                "url": prog_url,
            }
        if opp_block or prog_block:
            connect_section = {"opportunity": opp_block, "program": prog_block}

    # ── Apps ──
    apps_list: list[dict] = []
    summaries_folder = _find_folder(run_children, "app-summaries")
    deployment_md = _find(run_children, "deployment-summary.md")
    deployment_text = _read_text(drive, deployment_md) if deployment_md else ""

    if summaries_folder is not None:
        try:
            summary_children = drive.list_files(summaries_folder.id)
        except Exception as exc:  # noqa: BLE001
            log.warning("summary: list app-summaries failed: %s", exc)
            summary_children = []
        for kind, filename in (
            ("Learn", "learn-app-summary.md"),
            ("Deliver", "deliver-app-summary.md"),
        ):
            f = _find(summary_children, filename)
            if f is None:
                continue
            body = _read_text(drive, f)
            fm = _parse_frontmatter(body)
            name = fm.get("display_name") or fm.get("name")
            if not name:
                # Fall back to first H1.
                for line in _strip_frontmatter(body).splitlines():
                    if line.startswith("# "):
                        name = line[2:].strip()
                        break
            apps_list.append({
                "kind": kind,
                "name": name or f"{kind} app",
                "nova_url": fm.get("nova_app_url"),
                "hq_url": _extract_hq_url(deployment_text, kind) if deployment_text else None,
            })

    # ── Training pack ──
    training_section: dict | None = None
    training_folder = _find_folder(run_children, "training-materials")
    deck_block: dict | None = None
    docs_blocks: list[dict] = []

    # The deck URL lives in run_state.yaml's training_deck block.
    state_md = _find(run_children, "run_state.yaml") or _find(run_children, "state.yaml")
    if state_md is not None:
        try:
            state = yaml.safe_load(_read_text(drive, state_md)) or {}
        except yaml.YAMLError:
            state = {}
        td = state.get("training_deck") or {}
        if td.get("web_view_link"):
            deck_block = {
                "title": td.get("title") or f"FLW training · {display_name}",
                "url": td.get("web_view_link"),
            }

    if training_folder is not None:
        try:
            tchildren = drive.list_files(training_folder.id)
        except Exception as exc:  # noqa: BLE001
            log.warning("summary: list training-materials failed: %s", exc)
            tchildren = []
        for f in tchildren:
            if _is_folder(f):
                continue
            title = _TRAINING_DOC_TITLES.get(f.name)
            if title is None:
                continue  # only list the canonical docs; skip ad-hoc files
            docs_blocks.append({"title": title, "url": f.web_view_link})
        # Stable ordering
        order = list(_TRAINING_DOC_TITLES.values())
        docs_blocks.sort(key=lambda d: order.index(d["title"]) if d["title"] in order else 99)

    if deck_block or docs_blocks:
        training_section = {"deck": deck_block, "docs": docs_blocks}

    # ── Assistant (OCS) ──
    assistant_section: dict | None = None
    ocs_config = _find(run_children, "ocs-agent-config.md")
    ocs_setup_folder = _find_folder(run_children, "ocs-setup")
    handoff_fm: dict = {}
    if ocs_setup_folder is not None:
        try:
            ocs_setup_children = drive.list_files(ocs_setup_folder.id)
        except Exception as exc:  # noqa: BLE001
            log.warning("summary: list ocs-setup failed: %s", exc)
            ocs_setup_children = []
        handoff_md = _find(ocs_setup_children, "widget-handoff.md")
        if handoff_md is not None:
            handoff_fm = _parse_frontmatter(_read_text(drive, handoff_md))

    if ocs_config is not None:
        cfg_fm = _parse_frontmatter(_read_text(drive, ocs_config))
        public_id = cfg_fm.get("public_id")
        embed_key = cfg_fm.get("embed_key")
        ocs_url = _ocs_standalone_url(public_id, handoff_fm)
        if public_id and embed_key:
            assistant_section = {
                "ocs_url": ocs_url,
                "public_id": public_id,
                "embed_key": embed_key,
            }

    # ── Open questions (opp-level, sibling of runs/) ──
    open_questions_section: dict | None = None
    oq_file = _find(opp_children, "open-questions.md")
    if oq_file is not None and oq_file.web_view_link:
        open_questions_section = {"url": oq_file.web_view_link}

    # ── Status (closed / active / in_progress) ──
    closeout_folder = _find_folder(run_children, "closeout")
    is_closed = False
    if closeout_folder is not None:
        try:
            cchildren = drive.list_files(closeout_folder.id)
        except Exception:  # noqa: BLE001
            cchildren = []
        is_closed = _find(cchildren, "cycle-grade.md") is not None

    if is_closed:
        status = "closed"
    elif end_date_iso and _is_future(end_date_iso):
        status = "active"
    else:
        status = "in_progress"

    # ── Workbench escape hatch ──
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
        "apps": apps_list,
        "connect": connect_section,
        "training": training_section,
        "assistant": assistant_section,
        "open_questions": open_questions_section,
        "workbench_url": workbench_url,
    }


def _is_future(date_iso: str) -> bool:
    """Return True if ``date_iso`` (YYYY-MM-DD) is on or after today.

    Tolerates malformed input by returning False (so the run reads as
    in_progress rather than active when we can't tell).
    """
    try:
        d = date.fromisoformat(str(date_iso)[:10])
    except (TypeError, ValueError):
        return False
    return d >= date.today()
