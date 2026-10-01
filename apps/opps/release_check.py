"""The run's release check — is it ready to share with the partner?

The ACE plugin's ``release-check`` skill makes one final pass across
everything a run produced (every QA/eval gate, the live Connect read-back,
output previews, every link as the partner would open it, the public summary)
and writes ONE verdict next to ``run_state.yaml``::

    <run>/release-check_verdict.yaml   (ReleaseVerdict v1, lib/release-check.ts)
    <run>/release-check_report.md      (the human-readable report, a Doc)

``/ace:release`` refuses to invite anyone without a READY verdict for that run,
so the Workbench shows it where the release decision is made. This module only
READS it: a missing or unreadable verdict is "not checked", never "ready".
"""
from __future__ import annotations

import logging
from typing import Any

import yaml

from apps.opps.drive_client import DriveClient, DriveFile

log = logging.getLogger(__name__)

VERDICT_NAME = "release-check_verdict.yaml"
REPORT_NAME = "release-check_report.md"
_ITEM_FIELDS = ("id", "area", "owner", "detail", "fix")
_MAX_ITEMS = 50


def load_release_check(client: DriveClient, run_children: list[DriveFile]) -> dict | None:
    """The run's latest release-check verdict, or None when it has none.

    ``{verdict, checked_at, run_last_write, read_only, counts, blockers,
    warnings, report}`` — ``report`` is ``{file_id, url}`` or None.
    """
    verdict_file = next((f for f in run_children if f.name == VERDICT_NAME), None)
    if verdict_file is None:
        return None
    try:
        text = client.get_content(verdict_file.id, verdict_file.mime_type).content
        data = yaml.safe_load(str(text).replace("\r\n\r\n\r\n", "\n").replace("\r\n", "\n"))
    except Exception:  # noqa: BLE001 — an unreadable verdict is "not checked"
        log.warning("release_check: could not read %s", VERDICT_NAME, exc_info=True)
        data = None
    if not isinstance(data, dict):
        return {"verdict": "UNREADABLE", "blockers": [], "warnings": [], "counts": {},
                "checked_at": None, "run_last_write": None, "read_only": False, "report": None}

    report = next((f for f in run_children if f.name == REPORT_NAME), None)
    verdict = str(data.get("verdict") or "").upper()
    return {
        "verdict": verdict if verdict in {"READY", "NOT_READY"} else "UNREADABLE",
        "checked_at": _str(data.get("checked_at")),
        "run_last_write": _str(data.get("run_last_write")),
        "read_only": bool(data.get("read_only")),
        "counts": {
            "blockers": _int((data.get("counts") or {}).get("blockers")),
            "warnings": _int((data.get("counts") or {}).get("warnings")),
        },
        "blockers": _items(data.get("blockers")),
        "warnings": _items(data.get("warnings")),
        "report": {"file_id": report.id, "url": report.web_view_link} if report else None,
    }


def _items(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:_MAX_ITEMS]:
        if isinstance(item, dict):
            out.append({k: _str(item.get(k)) for k in _ITEM_FIELDS})
    return out


def _str(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
