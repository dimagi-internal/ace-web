"""Reviewer feedback — what an outside expert said, and what it changed.

ACE grades its own work, and sometimes it is wrong in ways only an outsider
catches. On 2026-07-27 a domain expert reviewed `hh-poverty-targeting`: nine
comments produced six skill defects, three run decisions and one open question
— including one against a Learn-app assessment ACE's own eval had scored 9.4.
That loop is the most load-bearing thing about how ACE improves, and until now
it was invisible in the product: it lived in a Drive folder nobody opens.

This module surfaces it. Two files per review, both written by the plugin's
`feedback-ledger` skill under `ACE/<opp>/feedback/`:

  <slug>.yaml     the VERBATIM inbound record — reviewer, channel, and each
                  comment with the section it was anchored to. A fact store.
  <slug>-ledger   the DERIVED view — each comment joined against the GitHub
                  issues, decisions and open questions it produced.

**ace-web does not recompute the derived half.** The plugin owns that join
(it greps issue bodies for `Feedback-Ref: <record-slug>/<item-id>` stamps),
and a second implementation here would need a GitHub credential and would
drift from the one people actually run. We render what the plugin published,
the same way the run summary renders the build memo.

The ledger doc carries no file extension, so `drive_export.read_prose` would
not markdown-export it. We export explicitly, and — like the build memo — do
NOT unescape: the frontend resolves markdown escapes itself, and unescaping
before a CommonMark renderer damages the body.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import yaml

from apps.opps.drive_export import GOOGLE_DOC_MIME, MARKDOWN_EXPORT

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

FEEDBACK_FOLDER = "feedback"
_LEDGER_SUFFIX = "-ledger"

# The plugin's own headline line, e.g.
#   "9 comments — 8 shipped, 1 need a human, 0 unrouted."
# Read, never recomputed: the counts come from the join we deliberately do not
# reimplement. A miss yields None and the UI shows nothing rather than a number
# we cannot stand behind.
# "Responding run: `20260728-0705`" — which run actually acted on the review.
# Only the rendered ledger knows it (the inbound record predates the response),
# so like the tally it is READ, and absent rather than guessed.
_RESPONDING_RUN_RE = re.compile(
    r"Responding\s+run:\s*`?([0-9]{8}-[0-9]{4})`?", re.IGNORECASE
)

# The ledger's own items are H2s: "## \[a\] §3 Instrument — …".
_ITEM_HEADING_RE = re.compile(r"^##\s", re.MULTILINE)

_TALLY_RE = re.compile(
    r"(\d+)\s+comments?\s*[—–-]\s*(\d+)\s+shipped,\s*(\d+)\s+need[s]?\s+a\s+human,"
    r"\s*(\d+)\s+unrouted",
    re.IGNORECASE,
)


def _is_folder(f) -> bool:
    return getattr(f, "mime_type", "") == "application/vnd.google-apps.folder"


def find_feedback_folder(drive, opp_folder_id: str):
    """The opp's ``feedback/`` folder, or None when the opp has no reviews."""
    try:
        children = drive.list_folder(opp_folder_id)
    except Exception:  # noqa: BLE001 — a missing folder is not an error here
        log.warning("feedback: could not list opp folder %s", opp_folder_id)
        return None
    for f in children:
        if _is_folder(f) and f.name == FEEDBACK_FOLDER:
            return f
    return None


def parse_tally(body: str) -> dict | None:
    """The plugin's rendered counts, or None when the line isn't there."""
    m = _TALLY_RE.search(body or "")
    if not m:
        return None
    total, shipped, needs_human, unrouted = (int(g) for g in m.groups())
    return {
        "comments": total,
        "shipped": shipped,
        "needs_human": needs_human,
        "unrouted": unrouted,
    }


def parse_responding_run(body: str) -> str:
    """The run that acted on the review, or "" when the line isn't there."""
    m = _RESPONDING_RUN_RE.search(body or "")
    return m.group(1) if m else ""


def strip_ledger_preamble(body: str) -> str:
    """Drop the ledger's own header, keeping its items.

    The rendered doc opens with a do-not-edit notice, a title, the artifact
    line and the tally — all of which the panel's own header already shows
    from the structured record, and the last two of which we parse out
    separately. Rendering both reads as a stutter.

    Falls back to the whole body when no item heading is found, because half
    a ledger is worse than a repeated line.
    """
    m = _ITEM_HEADING_RE.search(body or "")
    return body[m.start():] if m else (body or "")


def _parse_record(text: str) -> dict | None:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        log.warning("feedback: record is not valid YAML")
        return None
    return data if isinstance(data, dict) else None


def _serialize_items(raw: Any) -> list[dict]:
    """The reviewer's comments, verbatim.

    Each item keeps the anchor it was left against, because a comment detached
    from the section it was about is much harder to act on — and much easier to
    argue with.
    """
    if not isinstance(raw, list):
        return []
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        items.append({
            "id": str(entry.get("id") or ""),
            "anchor": str(entry.get("anchor") or ""),
            "verbatim": str(entry.get("verbatim") or "").strip(),
        })
    return items


def build_feedback_payload(drive, opp_folder_id: str) -> dict:
    """Every review of this opp, newest first, each with its rendered ledger."""
    folder = find_feedback_folder(drive, opp_folder_id)
    if folder is None:
        return {"schema_version": SCHEMA_VERSION, "records": []}

    try:
        children = drive.list_folder(folder.id)
    except Exception:  # noqa: BLE001
        log.warning("feedback: could not list feedback folder %s", folder.id)
        return {"schema_version": SCHEMA_VERSION, "records": []}

    ledgers = {
        f.name[: -len(_LEDGER_SUFFIX)]: f
        for f in children
        if not _is_folder(f) and f.name.endswith(_LEDGER_SUFFIX)
    }

    records = []
    for f in children:
        if _is_folder(f) or not f.name.endswith((".yaml", ".yml")):
            continue
        try:
            text = drive.get_content(f.id, f.mime_type).content or ""
        except Exception:  # noqa: BLE001
            log.warning("feedback: could not read record %s", f.name)
            continue
        data = _parse_record(text)
        if data is None:
            continue

        slug = str(data.get("slug") or f.name.rsplit(".", 1)[0])
        ledger_file = ledgers.get(slug)
        ledger_body = ""
        if ledger_file is not None:
            try:
                export_as = (
                    MARKDOWN_EXPORT if ledger_file.mime_type == GOOGLE_DOC_MIME else None
                )
                ledger_body = (
                    drive.get_content(
                        ledger_file.id, ledger_file.mime_type, export_as=export_as
                    ).content
                    or ""
                )
            except Exception:  # noqa: BLE001
                log.warning("feedback: could not read ledger for %s", slug)

        items = _serialize_items(data.get("items"))
        records.append({
            "slug": slug,
            "reviewer": str(data.get("reviewer") or ""),
            "reviewer_email": str(data.get("reviewer_email") or ""),
            "received_at": str(data.get("received_at") or ""),
            "channel": str(data.get("channel") or ""),
            "artifact": str(data.get("artifact") or ""),
            "artifact_url": str(data.get("artifact_url") or ""),
            "against_run": str(data.get("against_run") or ""),
            "items": items,
            "item_count": len(items),
            # Both READ from the plugin's rendered ledger, never recomputed.
            "tally": parse_tally(ledger_body),
            "responding_run": parse_responding_run(ledger_body),
            "ledger_body": strip_ledger_preamble(ledger_body),
            "ledger_url": getattr(ledger_file, "web_view_link", "") if ledger_file else "",
            "record_url": getattr(f, "web_view_link", "") or "",
        })

    records.sort(key=lambda r: r["received_at"], reverse=True)
    return {"schema_version": SCHEMA_VERSION, "records": records}
