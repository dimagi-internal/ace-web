"""The run's release-readiness verdict — is it ready to share with the partner?

The ACE plugin's ``validate-release-readiness`` skill (formerly
``release-check``) makes one final pass across everything a run produced
(every QA/eval gate, the live Connect read-back, output previews, every link as
the partner would open it, the public summary) and does every piece of work a
release could cause EXCEPT sharing. It writes ONE verdict next to
``run_state.yaml``::

    <run>/release-readiness_verdict.yaml   (schema_version 2, kind release-readiness)
    <run>/release-readiness_report.md      (the human-readable report, a Doc)

Older runs carry the legacy pair, still read as a fallback::

    <run>/release-check_verdict.yaml       (ReleaseVerdict v1)
    <run>/release-check_report.md

A READY v2 verdict carries a ``release_plan``: the exact, ordered share actions
``/ace:release`` will execute and nothing else (HQ / Connect / Drive / ace-web
invites, the forward-source link, the emails). A READY v1 verdict has no plan,
so it is NOT ready — ``/ace:release`` needs a plan.

``/ace:release`` refuses to invite anyone without a READY verdict for that run,
so the Workbench shows it where the release decision is made. This module only
READS it: a missing or unreadable verdict is "not checked", never "ready", and
a malformed part of a verdict degrades to "not shown", never an error.
"""
from __future__ import annotations

import logging
from typing import Any

import yaml

from apps.opps.drive_client import DriveClient, DriveFile

log = logging.getLogger(__name__)

#: (verdict, report, kind) — the new name first; the legacy pair is the
#: fallback, and a report is only ever paired with the verdict it sits beside.
_FILE_PAIRS = (
    ("release-readiness_verdict.yaml", "release-readiness_report.md", "release-readiness"),
    ("release-check_verdict.yaml", "release-check_report.md", "release-check"),
)
VERDICT_NAME = _FILE_PAIRS[0][0]
REPORT_NAME = _FILE_PAIRS[0][1]
LEGACY_VERDICT_NAME = _FILE_PAIRS[1][0]
LEGACY_REPORT_NAME = _FILE_PAIRS[1][1]

#: ``summary`` / ``action`` are the plain-language sentence and next step ACE
#: adds per item (2026-10); older verdicts carry only ``detail`` / ``fix``,
#: and the dialog falls back to those.
_ITEM_FIELDS = ("id", "area", "severity", "owner", "detail", "fix", "summary", "action")
_MAX_ITEMS = 50

_MAX_REVIEWERS = 50
_MAX_ACTIONS = 200
_MAX_NOT_GRANTED = 200
_MAX_EMAILS = 50
_MAX_BODY = 10_000
_MAX_FIELD = 2_000
#: Share-action string fields the dialog may show; every one but the first
#: four is optional. ``shared`` / ``cross_workspace`` are the bool fields.
_ACTION_STR_FIELDS = ("id", "system", "kind", "email", "target", "role", "title", "url", "scope",
                      "subject")
_ACTION_BOOL_FIELDS = ("shared", "cross_workspace")
_OPTION_FIELDS = ("forward_source", "allow_cross_workspace_forward", "allow_shared_connect")


def load_release_check(client: DriveClient, run_children: list[DriveFile]) -> dict | None:
    """The run's latest release-readiness verdict, or None when it has none.

    ``{kind, verdict, checked_at, run_last_write, read_only, counts, blockers,
    warnings, reviewers, release_plan, report}`` — ``report`` is
    ``{file_id, url}`` or None; ``release_plan`` is the sanitized plan or None
    (always None unless the verdict is READY).
    """
    by_name = {f.name: f for f in run_children}
    pair = next(((v, r, k) for v, r, k in _FILE_PAIRS if v in by_name), None)
    if pair is None:
        return None
    verdict_name, report_name, kind = pair
    verdict_file = by_name[verdict_name]
    report = by_name.get(report_name)
    report_ref = {"file_id": report.id, "url": report.web_view_link} if report else None
    try:
        text = client.get_content(verdict_file.id, verdict_file.mime_type).content
        data = yaml.safe_load(str(text).replace("\r\n\r\n\r\n", "\n").replace("\r\n", "\n"))
    except Exception:  # noqa: BLE001 — an unreadable verdict is "not checked"
        log.warning("release_check: could not read %s", verdict_name, exc_info=True)
        data = None
    if not isinstance(data, dict):
        return {"kind": kind, "verdict": "UNREADABLE", "blockers": [], "warnings": [],
                "counts": {}, "checked_at": None, "run_last_write": None, "read_only": False,
                "reviewers": [], "release_plan": None, "report": report_ref}

    verdict = str(data.get("verdict") or "").upper()
    verdict = verdict if verdict in {"READY", "NOT_READY"} else "UNREADABLE"
    counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    try:
        plan = _plan(data.get("release_plan")) if verdict == "READY" else None
    except Exception:  # noqa: BLE001 — a malformed plan is "not shown"
        log.warning("release_check: could not sanitize release_plan", exc_info=True)
        plan = None
    return {
        "kind": kind,
        "verdict": verdict,
        "checked_at": _str(data.get("checked_at")),
        "run_last_write": _str(data.get("run_last_write")),
        "read_only": bool(data.get("read_only")),
        "counts": {
            "blockers": _int(counts.get("blockers")),
            "warnings": _int(counts.get("warnings")),
        },
        "blockers": _items(data.get("blockers")),
        "warnings": _items(data.get("warnings")),
        "reviewers": _reviewers(data.get("reviewers")),
        "release_plan": plan,
        "report": report_ref,
    }


def _items(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:_MAX_ITEMS]:
        if isinstance(item, dict):
            row: dict[str, Any] = {k: _str(item.get(k)) for k in _ITEM_FIELDS}
            # ``merged`` is the list of finding ids folded into this one.
            merged = item.get("merged")
            row["merged"] = (
                [s for s in (_str(m) for m in merged[:_MAX_ITEMS]) if s]
                if isinstance(merged, list) else []
            )
            out.append(row)
    return out


def _reviewers(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for r in raw[:_MAX_REVIEWERS]:
        if isinstance(r, dict) and _str(r.get("email")):
            out.append({"email": _str(r.get("email")), "role": _str(r.get("role"))})
    return out


def _plan(raw: Any) -> dict | None:
    """The sanitized release plan, or None when there is none to show."""
    if not isinstance(raw, dict):
        return None
    actions = []
    for a in (raw.get("actions") if isinstance(raw.get("actions"), list) else [])[:_MAX_ACTIONS]:
        if not isinstance(a, dict):
            continue
        row: dict[str, Any] = {"step": _int(a.get("step")) or None}
        row.update({k: _str(a.get(k)) for k in _ACTION_STR_FIELDS})
        row.update({k: a[k] for k in _ACTION_BOOL_FIELDS if isinstance(a.get(k), bool)})
        if row["system"] and row["kind"]:
            actions.append(row)
    not_granted = []
    raw_ng = raw.get("not_granted") if isinstance(raw.get("not_granted"), list) else []
    for n in raw_ng[:_MAX_NOT_GRANTED]:
        if isinstance(n, dict) and _str(n.get("system")):
            not_granted.append({k: _str(n.get(k)) for k in ("email", "system", "reason")})
    emails = []
    for e in (raw.get("emails") if isinstance(raw.get("emails"), list) else [])[:_MAX_EMAILS]:
        if isinstance(e, dict) and _str(e.get("to")):
            emails.append({
                "to": _str(e.get("to")),
                "subject": _str(e.get("subject")),
                "body": _body(e.get("body")),
            })
    raw_opts = raw.get("options") if isinstance(raw.get("options"), dict) else {}
    options = {k: raw_opts[k] for k in _OPTION_FIELDS if isinstance(raw_opts.get(k), bool)}
    return {
        "reviewers": _reviewers(raw.get("reviewers")),
        "options": options,
        "actions": actions,
        "not_granted": not_granted,
        "emails": emails,
    }


def _body(value: Any) -> str | None:
    """An email body, whitespace preserved (the dialog renders it ``pre-wrap``)."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value[:_MAX_BODY]


def _str(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text[:_MAX_FIELD] or None


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
