"""Durable save of buffered decision edits to Drive (issue #673, PR 2).

Implements the write + read halves of
``docs/specs/2026-07-24-decision-review-save-design.md``:

* ``save_decision_overrides`` reads the Redis shared buffer
  (``apps/opps/decisions_buffer``) as the authoritative edit set, joins
  each buffered row against the source run's ``decisions.yaml`` to
  recover ``phase`` / ``question`` / ``ai_default`` (the buffer doesn't
  carry them), and merges the result into
  ``<opp>/inputs/decision-overrides.yaml``.

  ``inputs/`` and not the run folder: a fresh ``/ace:run`` reads the
  opp-level ``inputs/`` evidence pack and never reads a prior run's
  ``decisions.yaml``, so overrides parked in a run folder would be
  invisible to the next run. See the spec's "Why inputs/, not the run
  folder".

* ``fetch_saved_overrides`` is the read side — it locates the file under
  ``inputs/`` and returns ``{row_id: {...}}`` for snapshot injection.
  Missing folder, missing file, and malformed YAML all degrade to "no
  saved overrides" rather than an error.

The file is inert until the ACE plugin is taught to read it (deferred —
a PR in dimagi-internal/ace). The UI must not imply otherwise.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import yaml

from apps.opps.decisions_buffer import clear_edits, get_edits
from apps.opps.sync import _find_child, _find_child_folder

log = logging.getLogger(__name__)

OVERRIDES_FILENAME = "decision-overrides.yaml"
_YAML_MIME = "application/x-yaml"


class DecisionOverridesError(Exception):
    """Caller-friendly validation failure. ``code`` maps to HTTP status."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def build_override_rows(
    edits: dict[str, dict],
    decisions_rows: list[Any],
    *,
    source_run_id: str,
) -> list[dict]:
    """Join buffered edits against the run's decision rows.

    The buffer carries only ``{new_answer, override_reasoning,
    editor_email, editor_name, edited_at}`` per row_id; ``phase``,
    ``question``, and ``ai_default`` are denormalized from
    ``decisions.yaml`` so the file explains itself a year later without
    resolving a run folder that may be gone.

    Buffered row_ids missing from ``decisions.yaml`` are skipped (same
    posture as the forker's ``apply_edits_to_decisions_data`` — we can't
    synthesize a decision row out of thin air) with a warning.
    """
    by_id: dict[str, dict] = {}
    for row in decisions_rows:
        if isinstance(row, dict) and row.get("id"):
            by_id[row["id"]] = row

    out: list[dict] = []
    for row_id, edit in edits.items():
        source = by_id.get(row_id)
        if source is None:
            log.warning(
                "decision-overrides: buffered row %r not in decisions.yaml "
                "for run %s — skipped", row_id, source_run_id,
            )
            continue
        ai_default = source.get("ai-default", source.get("default", ""))
        row: dict[str, Any] = {
            "id": row_id,
            "phase": source.get("phase", ""),
            "question": source.get("question", ""),
            "ai_default": ai_default,
            "override": edit.get("new_answer", ""),
        }
        reasoning = (edit.get("override_reasoning") or "").strip()
        if reasoning:
            row["override_reasoning"] = reasoning
        row["decided_by"] = edit.get("editor_email", "")
        row["decided_at"] = edit.get("edited_at", "")
        row["source_run_id"] = source_run_id
        out.append(row)
    return out


def merge_overrides(existing: list[Any], new_rows: list[dict]) -> list[dict]:
    """Merge by ``id``, last write wins, preserving first-seen order.

    A row whose ``override`` equals ``ai_default`` with no reasoning is
    dropped entirely — that is a revert, and a revert leaves no trace
    beyond absence.
    """
    order: list[str] = []
    by_id: dict[str, dict] = {}
    for row in list(existing) + list(new_rows):
        if not isinstance(row, dict) or not row.get("id"):
            continue
        row_id = row["id"]
        if row_id not in by_id:
            order.append(row_id)
        by_id[row_id] = row

    merged: list[dict] = []
    for row_id in order:
        row = by_id[row_id]
        reverted = (
            row.get("override") == row.get("ai_default")
            and not (row.get("override_reasoning") or "").strip()
        )
        if reverted:
            continue
        merged.append(row)
    return merged


def render_overrides_yaml(opp_slug: str, rows: list[dict]) -> str:
    return yaml.safe_dump(
        {
            "schema_version": 1,
            "kind": "decision-overrides",
            "opp": opp_slug,
            "updated_at": datetime.now(UTC).isoformat(),
            "overrides": rows,
        },
        sort_keys=False,
        allow_unicode=True,
    )


def _parse_overrides_body(body: str) -> list[Any]:
    """Parse an existing decision-overrides.yaml body, tolerating junk.

    A malformed existing file yields ``[]`` — its content is
    unrecoverable either way, and blocking the reviewer's save behind a
    corrupt file would be worse than replacing it.
    """
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError:
        log.warning("decision-overrides: existing file is malformed YAML; treating as empty")
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("overrides")
    return rows if isinstance(rows, list) else []


def _load_run_decisions_rows(drive, opp_folder_id: str, opp_slug: str,
                             source_run_id: str) -> list[Any]:
    """Read + parse ``runs/<source_run_id>/decisions.yaml``."""
    opp_children = drive.list_files(opp_folder_id)
    runs_folder = _find_child_folder(opp_children, "runs")
    if runs_folder is None:
        raise DecisionOverridesError(
            "run-not-found", f"opp {opp_slug!r} has no runs/ subfolder",
        )
    run_folder = _find_child_folder(drive.list_files(runs_folder.id), source_run_id)
    if run_folder is None:
        raise DecisionOverridesError(
            "run-not-found",
            f"opp {opp_slug!r} has no run named {source_run_id!r}",
        )
    run_children = drive.list_files(run_folder.id)
    decisions_file = _find_child(run_children, "decisions.yaml") or _find_child(
        run_children, "decisions.yml",
    )
    if decisions_file is None:
        raise DecisionOverridesError(
            "decisions-not-found",
            f"run {source_run_id!r} has no decisions.yaml to join edits against",
        )
    # Pass the file's OWN mime type (get_content's contract) — real opps
    # carry Docs-typed decisions.yaml files, which are export-only and 403
    # on a raw download if we claim they're plain YAML.
    body = drive.get_content(decisions_file.id, decisions_file.mime_type).content
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        raise DecisionOverridesError(
            "decisions-unreadable",
            f"run {source_run_id!r} decisions.yaml is not valid YAML",
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("decisions"), list):
        raise DecisionOverridesError(
            "decisions-unreadable",
            f"run {source_run_id!r} decisions.yaml has no decisions list",
        )
    return data["decisions"]


def save_decision_overrides(
    *,
    drive,
    ace_root_folder_id: str,
    opp_slug: str,
    source_run_id: str,
) -> dict:
    """Persist the run's buffered edits to ``<opp>/inputs/decision-overrides.yaml``.

    Returns ``{"file_id", "override_count", "overrides"}``. An empty
    buffer is a no-op — no folder creation, no file write, nothing
    cleared. On success the Redis buffer is cleared; the read-side
    overlay (``fetch_saved_overrides``) keeps the UI honest afterward.
    """
    edits = get_edits(opp_slug, source_run_id)
    if not edits:
        return {"file_id": None, "override_count": 0, "overrides": []}

    opp_folder = _find_child_folder(
        drive.list_files(ace_root_folder_id), opp_slug,
    )
    if opp_folder is None:
        raise DecisionOverridesError(
            "opp-not-found", f"no opp folder named {opp_slug!r}",
        )

    decisions_rows = _load_run_decisions_rows(
        drive, opp_folder.id, opp_slug, source_run_id,
    )
    new_rows = build_override_rows(
        edits, decisions_rows, source_run_id=source_run_id,
    )

    opp_children = drive.list_files(opp_folder.id)
    inputs_folder = _find_child_folder(opp_children, "inputs")
    existing_file = None
    existing_rows: list[Any] = []
    if inputs_folder is not None:
        existing_file = _find_child(
            drive.list_files(inputs_folder.id), OVERRIDES_FILENAME,
        )
        if existing_file is not None:
            existing_rows = _parse_overrides_body(
                drive.get_content(existing_file.id, existing_file.mime_type).content,
            )

    merged = merge_overrides(existing_rows, new_rows)

    file_id: str | None = existing_file.id if existing_file else None
    if merged or existing_file is not None:
        body = render_overrides_yaml(opp_slug, merged)
        if existing_file is not None:
            drive.update_file(existing_file.id, body, _YAML_MIME)
        else:
            if inputs_folder is not None:
                inputs_folder_id = inputs_folder.id
            else:
                inputs_folder_id = drive.create_folder(opp_folder.id, "inputs")
            file_id = drive.upload_file(
                inputs_folder_id, OVERRIDES_FILENAME, body, _YAML_MIME,
            )

    clear_edits(opp_slug, source_run_id)
    return {
        "file_id": file_id,
        "override_count": len(merged),
        "overrides": merged,
    }


def fetch_saved_overrides(client, *, opp_folder_id: str) -> dict[str, dict]:
    """Read ``inputs/decision-overrides.yaml`` for snapshot injection.

    Returns ``{row_id: {override, reasoning, decided_by, decided_at,
    source_run_id}}``. Missing ``inputs/`` folder, missing file, and
    malformed YAML each degrade to ``{}`` — "no saved overrides" is a
    normal state, never an error. Drive transport failures propagate to
    the caller (the freshness-overlay machinery preserves the cached
    value on exceptions; direct callers guard themselves).
    """
    inputs_folder = _find_child_folder(client.list_files(opp_folder_id), "inputs")
    if inputs_folder is None:
        return {}
    overrides_file = _find_child(
        client.list_files(inputs_folder.id), OVERRIDES_FILENAME,
    )
    if overrides_file is None:
        return {}
    rows = _parse_overrides_body(
        client.get_content(overrides_file.id, overrides_file.mime_type).content,
    )
    out: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        out[row["id"]] = {
            "override": row.get("override", ""),
            "reasoning": row.get("override_reasoning", ""),
            "decided_by": row.get("decided_by", ""),
            "decided_at": row.get("decided_at", ""),
            "source_run_id": row.get("source_run_id", ""),
        }
    return out
