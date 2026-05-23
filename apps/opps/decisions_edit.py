"""Apply human answer overrides to a parsed decisions.yaml dict.

Pure helper — no YAML, no Drive, no Django. Called from the forker
after the trim step. Matches the override contract used by the
``decisions-sync`` skill in the ACE plugin (schema v2):

* ``override`` is set to the new value (a separate field; ``ai-default``
  stays as the AI's original proposal).
* ``status`` flips to ``"overridden"``.
* If the new value matches the existing ``ai-default``, ``override`` is
  cleared and ``status`` reverts to ``"ai-default"`` (revert path).
"""
from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any


def apply_edits_to_decisions_data(
    data: dict[str, Any],
    *,
    edits: Iterable[dict[str, str]],
) -> dict[str, Any]:
    """Return a deep-copied dict with edits applied.

    Args:
        data: Parsed decisions.yaml as a dict (must contain ``decisions``
            list). Caller is expected to have upgraded v1 input to v2
            shape (see ``upgrade_decisions_v1_to_v2`` in this module).
        edits: Iterable of ``{"row_id": ..., "new_answer": ...}``.

    Unknown row_ids are silently ignored — the forker has no way to
    synthesize a new decision row out of thin air; the source must
    already contain it.
    """
    edits_list = list(edits)
    if not edits_list:
        return data

    rows = data.get("decisions")
    if not isinstance(rows, list):
        return data

    out = copy.deepcopy(data)
    out_rows = out["decisions"]

    edit_by_id = {e["row_id"]: e["new_answer"] for e in edits_list}

    for row in out_rows:
        if not isinstance(row, dict):
            continue
        row_id = row.get("id")
        if row_id not in edit_by_id:
            continue
        new_answer = edit_by_id[row_id]
        ai_default = row.get("ai-default")
        if new_answer == ai_default:
            row.pop("override", None)
            row["status"] = "ai-default"
        else:
            row["override"] = new_answer
            row["status"] = "overridden"

    return out


def upgrade_decisions_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """In-memory upgrade of a v1 decisions log dict to the v2 shape.

    v1 → v2:
      * row field rename: ``default`` → ``ai-default``
      * status enum: ``applied`` / ``open`` → ``ai-default``
      * for status=overridden rows missing ``override:``, copy the v1
        ``default`` value into ``override`` (lossy: v1 destroyed the
        original AI value on override, so the migrated row carries the
        same value in both ``ai-default`` and ``override``)
      * ``schema_version`` bumped to 2
    """
    if not isinstance(data, dict):
        return data
    if data.get("schema_version") == 2:
        return data
    if data.get("schema_version") not in (None, 1):
        return data

    out = copy.deepcopy(data)
    rows = out.get("decisions")
    if not isinstance(rows, list):
        return out

    upgraded_rows: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            upgraded_rows.append(row)
            continue
        new_row = dict(row)
        if "default" in new_row and "ai-default" not in new_row:
            new_row["ai-default"] = new_row.pop("default")
        if new_row.get("status") != "overridden":
            new_row["status"] = "ai-default"
        if new_row.get("status") == "overridden" and "override" not in new_row:
            ai_default = new_row.get("ai-default")
            if isinstance(ai_default, str):
                new_row["override"] = ai_default
        upgraded_rows.append(new_row)

    out["decisions"] = upgraded_rows
    out["schema_version"] = 2
    return out
