"""Apply human answer overrides to a parsed decisions.yaml dict.

Pure helper — no YAML, no Drive, no Django. Called from the forker
after the trim step. Matches the override contract used by the
``decisions-sync`` skill in the ACE plugin:

* ``default`` is set to the new value.
* ``status`` flips to ``"overridden"``.
* The pre-edit ``default`` value is preserved in ``options_considered``
  (deduplicated; only the *original* default is kept across repeat
  overrides — not the intermediate values).
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
        data: Parsed decisions.yaml as a dict (must contain ``decisions`` list).
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
        prior_default = row.get("default")
        options = row.get("options_considered") or []
        if not isinstance(options, list):
            options = []
        # Preserve the *original* default in options. If the row is already
        # overridden, its options list already contains the original — don't
        # add the intermediate value.
        if row.get("status") != "overridden":
            if prior_default is not None and prior_default not in options:
                options = [*options, prior_default]
        row["default"] = new_answer
        row["status"] = "overridden"
        row["options_considered"] = options

    return out
