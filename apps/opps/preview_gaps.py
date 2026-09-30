"""Which of a run's outputs the page can't show — the capture skill's work list.

The rule (docs/specs/2026-09-29-output-previews-design.md, addendum): every
output ace-web lists is either a file the in-page viewer draws, or has one or
more screenshots. An output that is neither is a GAP. The ACE plugin's
``output-preview-capture`` skill asks this for a run and photographs what is
missing, so the list is computed HERE, from the same products catalogue and
the same viewability rule the page uses — a writer that re-derived either
would drift, and the drift would look like a picture that never shows up.

Each gap carries ``output_key`` — exactly the key an index must name for
ace-web to attach its frames — and ``auth``, which signed-in session can open
``url``.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from apps.opps import artifact_view
from apps.opps.drive_client import DriveClient

log = logging.getLogger(__name__)

#: Kinds whose ``file_id`` IS the output (a Drive file the viewer may draw).
#: Every other kind is a live thing in another system, shown by screenshots.
_FILE_KINDS = frozenset({"document", "deck", "sheet", "link"})


def auth_for(url: str | None) -> str:
    """Which session opens ``url``: connect | labs | canopy | hq | ocs |
    google | public. canopy is served under the labs host but signs in on
    its own — a labs session is sent to Google sign-in there."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if host == "connect.dimagi.com":
        return "connect"
    if host == "labs.connect.dimagi.com":
        return "canopy" if (parsed.path or "").startswith("/canopy/") else "labs"
    if host.endswith("commcarehq.org"):
        return "hq"
    if host.endswith("openchatstudio.com"):
        return "ocs"
    if host in {"drive.google.com", "docs.google.com"}:
        return "google"
    return "public"


def build_preview_gaps(snapshot: dict, drive: DriveClient) -> dict:
    """``{run_id, outputs: [gap…], covered}`` for one rich snapshot.

    A Drive file counts as shown when the viewer can draw its type and size
    (``artifact_view.is_viewable``); that needs its metadata, one cached
    ``get_file`` per file output. A metadata read that fails is reported as a
    gap rather than assumed fine — a false "covered" hides a missing picture.
    """
    run = snapshot.get("current_run") or {}
    outputs: list[dict] = []
    covered = 0
    for product in run.get("products") or []:
        if not isinstance(product, dict):
            continue
        if product.get("previews"):
            covered += 1
            continue
        reason = _file_gap(product, drive)
        if reason is None:
            covered += 1
            continue
        outputs.append(_gap(product, reason))
    return {"run_id": run.get("run_id"), "outputs": outputs, "covered": covered}


def _file_gap(product: dict, drive: DriveClient) -> str | None:
    """None when the page shows this output as a file; else the gap reason."""
    file_id = product.get("file_id")
    if not file_id or product.get("kind") not in _FILE_KINDS:
        return "no-preview"
    try:
        f = drive.get_file(str(file_id))
    except Exception:  # noqa: BLE001 — unknown is a gap, never "covered"
        log.warning("preview_gaps: metadata for %s unavailable", file_id, exc_info=True)
        return "not-viewable-file"
    meta = artifact_view.FileMeta(
        file_id=str(file_id),
        name=f.name or "",
        mime_type=f.mime_type or "",
        web_link=f.web_view_link or None,
        size_bytes=f.size_bytes,
    )
    return None if artifact_view.is_viewable(meta) else "not-viewable-file"


def _gap(product: dict, reason: str) -> dict[str, Any]:
    url = product.get("url")
    return {
        "id": product.get("id"),
        "phase": product.get("phase"),
        "output_key": product.get("key"),
        "kind": product.get("kind"),
        "title": product.get("title"),
        "url": url,
        # The page anyone can open, when there is one (a chatbot's anonymous
        # chat): what a screenshot should show, rather than an admin page.
        "public_url": product.get("public_url"),
        "file_id": product.get("file_id"),
        "reason": reason,
        "auth": "google" if reason == "not-viewable-file" else auth_for(url),
    }
