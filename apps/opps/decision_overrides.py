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

The plugin consumes the file at the decisions write boundary
(`lib/decision-overrides.ts` → `decisions_append_rows`, ace#933), so a
saved override binds to whatever runs next for the opp.

## Two surfaces, one store (2026-08-14)

This module is now the store for BOTH editing surfaces:

* the **Workbench** (authenticated member, multi-player Redis staging
  buffer, explicit "Save to Drive"), and
* the **public run summary** (`?tab=decisions`), where anyone with the
  link can change a value in place — no proposal state, no promotion
  step, no member-only privilege.

That is a deliberate reversal of the earlier "an anonymous self-asserted
name must not silently rewrite the next run's inputs" rule (Jonathan,
2026-08-14). The bar to start engaging with ACE has to be very low
because it is speculative AI work: an account requirement is a barrier, a
name field is not. And the PDD — the document these decisions summarize
— is *already* world-editable via anyone-with-link and already seeds the
next run, so gating the decisions UI more tightly than the design
document itself was backwards.

**Safety here is visibility and reversibility, not permission** — exactly
as it is in a Google Doc. That is what the two additions to the row shape
buy, and why they are not optional polish:

* ``decided_by_name`` + ``decided_by_verified`` — every row says who last
  changed it and whether that identity was authenticated or self-reported.
* ``history`` — newest-first snapshots of every prior state of the row, so
  a previous value is always recoverable and any change can be undone from
  the UI. A **revert** (back to the AI default, no reasoning) is written as
  a real row rather than as absence whenever the row has history, so the
  fact that someone reverted it stays visible; the plugin's
  ``applyDecisionOverrides`` skips such a row by construction, so it is
  inert for the next run while staying legible here.

Both fields are additive and ``schema_version`` stays **1**:
``DecisionOverrideRowSchema`` in the plugin is a non-strict zod object, so
it strips what it doesn't know, and it fail-louds on any other
``schema_version``. Do not bump it without a paired plugin change.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import yaml

from apps.opps.decisions_buffer import clear_edits, get_edits
from apps.opps.public_input import Reviewer, clean_text
from apps.opps.sync import _find_child, _find_child_folder

log = logging.getLogger(__name__)

OVERRIDES_FILENAME = "decision-overrides.yaml"
_YAML_MIME = "application/x-yaml"

#: Newest-first prior states kept per row. History is what makes an
#: unauthenticated edit safe (any change is inspectable and undoable), so
#: it is not optional — but it is also the only unbounded axis a public
#: writer controls in this file, hence a cap. 25 x 42 rows is a file a
#: human can still open.
MAX_HISTORY_PER_ROW = 25

#: An override VALUE is an option label, not prose.
MAX_VALUE_CHARS = 400
#: The rationale is prose, and shares the reactions surface's ceiling.
MAX_REASONING_CHARS = 2000

#: Fields snapshotted into ``history`` when a row is superseded.
_HISTORY_FIELDS = (
    "override",
    "override_reasoning",
    "decided_by",
    "decided_by_name",
    "decided_by_verified",
    "decided_at",
    "source_run_id",
)


class DecisionOverridesError(Exception):
    """Caller-friendly validation failure. ``code`` maps to HTTP status."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _ai_default_of(source: dict) -> str:
    return str(source.get("ai-default", source.get("default", "")) or "")


def make_override_row(
    *,
    row_id: str,
    source: dict,
    value: str,
    reasoning: str,
    reviewer: Reviewer,
    decided_at: str,
    source_run_id: str,
) -> dict:
    """One override row, in the shape both surfaces write.

    ``phase`` / ``question`` / ``ai_default`` are denormalized from the
    run's ``decisions.yaml`` so the file explains itself a year later
    without resolving a run folder that may be gone. The plugin never
    matches on them (`lib/decision-overrides.ts`: "Row identity is ``id``
    alone").

    ``decided_by_name`` + ``decided_by_verified`` are the identity half:
    a signed-in member and a partner who typed their name both get to
    change the value, and the row records which one it was rather than
    flattening them into an email field one of them can't fill.
    """
    row: dict[str, Any] = {
        "id": row_id,
        "phase": str(source.get("phase", "") or ""),
        "question": str(source.get("question", "") or ""),
        "ai_default": _ai_default_of(source),
        "override": value,
    }
    if reasoning:
        row["override_reasoning"] = reasoning
    row["decided_by"] = reviewer.email
    row["decided_by_name"] = reviewer.name
    row["decided_by_verified"] = reviewer.verified
    row["decided_at"] = decided_at
    row["source_run_id"] = source_run_id
    return row


def build_override_rows(
    edits: dict[str, dict],
    decisions_rows: list[Any],
    *,
    source_run_id: str,
) -> list[dict]:
    """Join buffered Workbench edits against the run's decision rows.

    The buffer carries only ``{new_answer, override_reasoning,
    editor_email, editor_name, edited_at}`` per row_id — everything else
    comes from ``decisions.yaml`` via ``make_override_row``, which is the
    same builder the public single-row path uses. One row shape, two
    callers.

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
        # A Workbench edit is always authenticated — the WebSocket
        # consumer closes an unauthenticated connect with 4001.
        reviewer = Reviewer(
            email=edit.get("editor_email", "") or "",
            name=edit.get("editor_name", "") or edit.get("editor_email", "") or "",
            verified=True,
        )
        out.append(make_override_row(
            row_id=row_id,
            source=source,
            value=edit.get("new_answer", ""),
            reasoning=(edit.get("override_reasoning") or "").strip(),
            reviewer=reviewer,
            decided_at=edit.get("edited_at", ""),
            source_run_id=source_run_id,
        ))
    return out


def _snapshot(row: dict) -> dict:
    """The subset of a row worth remembering once it's been superseded."""
    return {k: row[k] for k in _HISTORY_FIELDS if row.get(k) not in (None, "")}


def _is_revert(row: dict) -> bool:
    """Back to the AI default with nothing to say = a revert."""
    return (
        row.get("override") == row.get("ai_default")
        and not (row.get("override_reasoning") or "").strip()
    )


def merge_overrides(existing: list[Any], new_rows: list[dict]) -> list[dict]:
    """Merge by ``id``, last write wins, preserving first-seen order.

    Last-writer-wins is only acceptable because nothing is lost: when a
    row is superseded, its previous state is pushed onto the winner's
    ``history`` (newest first, capped at ``MAX_HISTORY_PER_ROW``), so
    reviewer 2 changing reviewer 1's answer leaves reviewer 1's answer
    recoverable from the UI. Any ``history`` on an incoming row is
    ignored — history is derived here, never supplied by a caller.

    A revert (back to ``ai_default``, no reasoning) is dropped ONLY when
    the row has no history. With history it is kept, so "someone reverted
    this" stays visible and undoable; the plugin skips such a row when
    binding, so it stays inert for the next run.
    """
    order: list[str] = []
    by_id: dict[str, dict] = {}
    for row in existing:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        row_id = row["id"]
        if row_id not in by_id:
            order.append(row_id)
        by_id[row_id] = row

    for row in new_rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        row_id = row["id"]
        prior = by_id.get(row_id)
        row = {k: v for k, v in row.items() if k != "history"}
        if prior is not None:
            history = [_snapshot(prior)]
            history.extend(
                h for h in (prior.get("history") or []) if isinstance(h, dict)
            )
            row["history"] = history[:MAX_HISTORY_PER_ROW]
        else:
            order.append(row_id)
        by_id[row_id] = row

    merged: list[dict] = []
    for row_id in order:
        row = by_id[row_id]
        if _is_revert(row) and not row.get("history"):
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


def _resolve_opp_folder(drive, ace_root_folder_id: str, opp_slug: str):
    opp_folder = _find_child_folder(
        drive.list_files(ace_root_folder_id), opp_slug,
    )
    if opp_folder is None:
        raise DecisionOverridesError(
            "opp-not-found", f"no opp folder named {opp_slug!r}",
        )
    return opp_folder


def write_override_rows(
    drive, *, opp_folder_id: str, opp_slug: str, new_rows: list[dict],
) -> dict:
    """Merge ``new_rows`` into ``<opp>/inputs/decision-overrides.yaml``.

    THE write path for both surfaces. Whether the rows came from the
    Workbench's Redis buffer or from one anonymous in-place edit on the
    public summary, they land in the same file, through the same merge,
    rendered by the same serializer — the surfaces differ only in how
    they resolved the identity that ends up on the row.

    Returns ``{"file_id", "override_count", "overrides"}``.
    """
    opp_children = drive.list_files(opp_folder_id)
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
                inputs_folder_id = drive.create_folder(opp_folder_id, "inputs")
            file_id = drive.upload_file(
                inputs_folder_id, OVERRIDES_FILENAME, body, _YAML_MIME,
            )

    return {
        "file_id": file_id,
        "override_count": len(merged),
        "overrides": merged,
    }


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

    opp_folder = _resolve_opp_folder(drive, ace_root_folder_id, opp_slug)
    decisions_rows = _load_run_decisions_rows(
        drive, opp_folder.id, opp_slug, source_run_id,
    )
    new_rows = build_override_rows(
        edits, decisions_rows, source_run_id=source_run_id,
    )
    result = write_override_rows(
        drive, opp_folder_id=opp_folder.id, opp_slug=opp_slug, new_rows=new_rows,
    )
    clear_edits(opp_slug, source_run_id)
    return result


def clean_override_value(raw: str | None) -> str:
    return clean_text(
        raw,
        field="Answer",
        min_chars=1,
        max_chars=MAX_VALUE_CHARS,
        too_short="Pick an option or type an answer.",
    )


def clean_override_reasoning(raw: str | None) -> str:
    if not str(raw or "").strip():
        return ""
    return clean_text(
        raw,
        field="Reason",
        min_chars=1,
        max_chars=MAX_REASONING_CHARS,
        too_short="Say a little more than that.",
    )


def apply_decision_edit(
    drive,
    *,
    ace_root_folder_id: str,
    opp_slug: str,
    source_run_id: str,
    decision_id: str,
    value: str,
    reasoning: str,
    reviewer: Reviewer,
    now: datetime | None = None,
) -> dict:
    """Change ONE decision's answer, from either surface, in place.

    The public counterpart to ``save_decision_overrides``: no staging
    buffer (an anonymous caller has no authenticated WebSocket to stage
    on, and a shared buffer that a member must later "Save" IS the
    promotion gate this design removed), so the edit goes straight to the
    same file through ``write_override_rows``.

    An edit naming a ``decision_id`` the run's ``decisions.yaml`` does not
    carry is REFUSED, not stored. The row would be unroutable: the plugin
    binds overrides by ``id`` as a run raises rows, so an id no run raises
    is a silent no-op that reads to its author like a change they made.

    Returns the merged row plus ``{"file_id", "reverted"}``.
    """
    value = clean_override_value(value)
    reasoning = clean_override_reasoning(reasoning)

    opp_folder = _resolve_opp_folder(drive, ace_root_folder_id, opp_slug)
    decisions_rows = _load_run_decisions_rows(
        drive, opp_folder.id, opp_slug, source_run_id,
    )
    source = next(
        (
            r for r in decisions_rows
            if isinstance(r, dict) and str(r.get("id") or "") == decision_id
        ),
        None,
    )
    if source is None:
        raise DecisionOverridesError(
            "decision-not-found",
            f"no decision named {decision_id!r} in run {source_run_id!r}",
        )

    row = make_override_row(
        row_id=decision_id,
        source=source,
        value=value,
        reasoning=reasoning,
        reviewer=reviewer,
        decided_at=(now or datetime.now(UTC)).isoformat(),
        source_run_id=source_run_id,
    )
    result = write_override_rows(
        drive, opp_folder_id=opp_folder.id, opp_slug=opp_slug, new_rows=[row],
    )
    merged = next(
        (r for r in result["overrides"] if r.get("id") == decision_id), row,
    )
    return {
        "file_id": result["file_id"],
        "opp_folder_id": opp_folder.id,
        # Projected here so the API layer never has to know the on-disk
        # row shape — and so a public caller cannot be handed an email by
        # a future field addition.
        "row": project_override(merged, include_email=False),
    }


def project_override(row: dict, *, include_email: bool) -> dict:
    """One saved override as a reader sees it.

    ``include_email`` is False on the public payload for the same reason
    ``read_reactions`` never projects ``reviewer_email``: a member's work
    address is not part of what a share link is meant to circulate. The
    NAME is always projected — attribution is the safety mechanism, so
    hiding it would defeat the model.
    """
    out = {
        "override": row.get("override", ""),
        "reasoning": row.get("override_reasoning", ""),
        "decided_by_name": row.get("decided_by_name", "")
        or (row.get("decided_by", "") if include_email else ""),
        "decided_by_verified": bool(row.get("decided_by_verified", False)),
        "decided_at": row.get("decided_at", ""),
        "source_run_id": row.get("source_run_id", ""),
        "is_revert": _is_revert(row),
        "history": [
            {
                "override": h.get("override", ""),
                "reasoning": h.get("override_reasoning", ""),
                "decided_by_name": h.get("decided_by_name", "")
                or (h.get("decided_by", "") if include_email else ""),
                "decided_by_verified": bool(h.get("decided_by_verified", False)),
                "decided_at": h.get("decided_at", ""),
            }
            for h in (row.get("history") or [])
            if isinstance(h, dict)
        ],
    }
    if include_email:
        out["decided_by"] = row.get("decided_by", "")
    return out


def fetch_saved_overrides(
    client, *, opp_folder_id: str, include_email: bool = True,
) -> dict[str, dict]:
    """Read ``inputs/decision-overrides.yaml`` for snapshot injection.

    Returns ``{row_id: {override, reasoning, decided_by, decided_by_name,
    decided_by_verified, decided_at, source_run_id, is_revert, history}}``.
    Missing ``inputs/`` folder, missing file, and malformed YAML each
    degrade to ``{}`` — "no saved overrides" is a normal state, never an
    error. Drive transport failures propagate to the caller (the
    freshness-overlay machinery preserves the cached value on exceptions;
    direct callers guard themselves).

    Both the Workbench snapshot and the public run summary read through
    here, so what one surface can see about who changed a decision, the
    other can too.
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
        out[row["id"]] = project_override(row, include_email=include_email)
    return out
