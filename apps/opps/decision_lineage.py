"""Decision lineage — how a run's decisions evolved across the runs before it.

A run is rarely built from nothing. A fork re-runs the tail of an earlier run
(``forked_from`` / ``forked_from_phase`` in ``run_state.yaml``), a seeded run
does the same for a chosen set of phases (``seeded_from``), and a clone copies
a whole run into another workspace (``clone.from {workspace, opp, run}``, or a
``RunClone`` row). Each hop carries decision rows forward, and the reviewer of
the newest run wants to know, per decision: did it come from an earlier run,
unchanged? Was it changed here? Did a person set it?

This module answers that from the decision logs themselves:

* :func:`build_lineage` (pure) takes the runs of the chain — newest first,
  each with its raw ``decisions.yaml`` rows — and returns, for every live row
  of the newest run, its **history** (the value in each earlier run, in order)
  and its **origin** (one of ``new`` / ``decided`` / ``carried`` /
  ``changed`` / ``reaffirmed`` / ``human``).
* :func:`load_chain` walks ``run_state.yaml`` lineage keys across Drive,
  crossing into the source workspace for a clone.
* :func:`shape_for_viewer` strips what a viewer may not see — links into
  workspaces they are not a member of, and, for a non-member, run ids and the
  per-decision history (outsiders get the badges and the strip, in plain words).

Matching rows across runs is the hard part, because ACE ids are NOT always
stable. In order:

1. **same id** — the row's own id in the earlier run;
2. **earlier id** — the id of a row this run's log marks as replaced by it
   (``superseded_by`` chains: ``connect-latitude-payment-amount`` →
   ``…-2208`` → ``…-spark`` on spark-facilitator);
3. **retired id** — the ``<id>-<source-run-id>`` shape a fork retires a row
   under, with the suffix stripped.

Anything else is reported as "no earlier match", never guessed at.

**A clone hop is not a run.** A clone is the SAME run copied into another
workspace (same run id, same decisions), so provenance traces THROUGH it: the
origin of a clone's row is the origin of its source's row, and "How this
decision evolved" shows a clone and its source as one entry (the source,
``copied_to`` the clone's workspace). The clone re-minting a Connect row for
the partner's own orgs (``<id>`` kept as ``<id>-<source-workspace>`` with
``superseded_by`` → a fresh ``<id>`` of the same value) is therefore not an
event either — only a value the copy actually CHANGED is reported, as
``changed`` with ``on_copy``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime

log = logging.getLogger(__name__)

#: How many hops back a chain is followed. A real chain is 2-4 deep
#: (spark-facilitator: clone → fork → fork); the cap only stops a cycle or
#: a corrupted pointer from walking forever.
MAX_HOPS = 8

#: How many runs of an opp the ``scope=opp`` history reads (newest first).
MAX_OPP_RUNS = 30

ORIGIN_KINDS = ("new", "decided", "carried", "changed", "reaffirmed", "human")

_HUMAN_STATUSES = ("overridden", "human-decided")
_RUN_ID_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})")
# A fork's archived id: ``<id>-<source-run-id>`` (``opp_forker._archive_suffix``
# lower-cases the run id), with an optional ``-2`` collision counter.
_RETIRED_SUFFIX_RE = re.compile(r"-(\d{8}-\d{4})(?:-\d+)?$")


# ─── Data ──────────────────────────────────────────────────────────


@dataclass
class ChainRun:
    """One run of the lineage chain, as read from Drive."""

    workspace: str
    opp: str
    run_id: str
    #: How THIS run was made from the next (older) one in the chain:
    #: ``forked`` | ``seeded`` | ``cloned``; ``""`` for the oldest run.
    via: str = ""
    #: The phase a fork / seed re-ran from (``commcare-setup``); ``""`` else.
    at_phase: str = ""
    #: The run's own creation date, ISO (``created`` in run_state), or
    #: derived from the run id.
    date: str = ""
    rows: list[dict] = field(default_factory=list)
    #: False when the run could not be read (a source workspace this
    #: deployment does not know, a trashed run). It is still named in the
    #: chain — a label, with no rows behind it.
    readable: bool = True
    #: In the lineage chain (True) or another run of the opp (``scope=opp``).
    in_lineage: bool = True
    #: ``(workspace, run_id)`` of the run this one is a CLONE of, when it is
    #: one — a clone and its source are one run (see the module docstring).
    #: For a chain run, ``via == "cloned"`` says the same about ``chain[i+1]``.
    clone_of: tuple[str, str] | None = None
    #: For a clone: the day it was copied (``YYYY-MM-DD``), ``""`` if unknown.
    #: Its ``date`` is the SOURCE's — a clone copies ``created`` verbatim.
    copied_date: str = ""


# ─── Pure helpers ──────────────────────────────────────────────────


def run_date(run_id: str, state: dict | None = None) -> str:
    """The run's date as ``YYYY-MM-DD``: ``created`` in its run_state, else
    the date encoded in a timestamped run id; ``""`` when neither says."""
    raw = str((state or {}).get("created") or "").strip()
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
    m = _RUN_ID_RE.match(run_id or "")
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return ""
    return ""


def _sid(row: dict) -> str:
    return str(row.get("id") or "").strip()


def _status(row: dict) -> str:
    from apps.opps.parsers import normalize_decision_status

    return normalize_decision_status(row.get("status"))


def effective_value(row: dict) -> str:
    """The value a row stands behind: a human's ``override`` when one is in
    force, else the AI default."""
    override = str(row.get("override") or "").strip()
    if override and _status(row) in _HUMAN_STATUSES:
        return override
    return str(row.get("ai-default") or row.get("ai_default") or "").strip()


def _norm(value: str) -> str:
    """Compare values ignoring case, spacing and trailing punctuation —
    "weekly" → "Weekly." is not a change (same rule as run compare)."""
    return re.sub(r"\s+", " ", value or "").strip().rstrip(".;:,").casefold()


def _predecessors(rows: list[dict], target: str) -> list[str]:
    """Ids of every row in ``rows`` whose ``superseded_by`` chain reaches
    ``target`` — the earlier names of one decision inside one log."""
    succ = {_sid(r): str(r.get("superseded_by") or "").strip() for r in rows if _sid(r)}
    out: list[str] = []
    for rid in succ:
        seen: set[str] = set()
        cur = rid
        while cur and cur not in seen:
            seen.add(cur)
            nxt = succ.get(cur, "")
            if nxt == target:
                out.append(rid)
                break
            cur = nxt
    return out


def _stripped(row_id: str) -> str | None:
    m = _RETIRED_SUFFIX_RE.search(row_id)
    return row_id[: m.start()] if m else None


@dataclass
class _Candidates:
    exact: str
    earlier: list[str]
    retired: list[str]

    @classmethod
    def for_row(cls, rows: list[dict], row_id: str) -> _Candidates:
        earlier = [p for p in _predecessors(rows, row_id) if p != row_id]
        retired = [s for s in (_stripped(i) for i in [row_id, *earlier]) if s]
        return cls(exact=row_id, earlier=earlier, retired=retired)

    def merged(self, older: _Candidates) -> _Candidates:
        """Keep the older candidate names as a fallback behind these."""
        earlier = list(dict.fromkeys([*self.earlier, older.exact, *older.earlier]))
        retired = list(dict.fromkeys([*self.retired, *older.retired]))
        return _Candidates(self.exact, [e for e in earlier if e != self.exact], retired)


def _match(rows: list[dict], cand: _Candidates) -> tuple[dict | None, str]:
    """The row in ``rows`` that is the same decision, and how it matched.

    A LIVE row is preferred at every tier; a superseded row is accepted only
    when no live one matches (the decision existed there, but as history).
    """
    by_id: dict[str, dict] = {}
    for r in rows:
        rid = _sid(r)
        if rid and rid not in by_id:
            by_id[rid] = r

    def first(ids: list[str]) -> dict | None:
        live = [by_id[i] for i in ids if i in by_id and not by_id[i].get("superseded_by")]
        if live:
            return live[0]
        hist = [by_id[i] for i in ids if i in by_id]
        return hist[0] if hist else None

    for how, ids in (("id", [cand.exact]), ("earlier-id", cand.earlier),
                     ("retired-id", cand.retired)):
        hit = first(ids)
        if hit is not None:
            return hit, how
    return None, ""


def _entry(run: ChainRun, row: dict | None, how: str) -> dict:
    base = {
        "workspace": run.workspace,
        "opp": run.opp,
        "run_id": run.run_id,
        "date": run.date,
        "in_lineage": run.in_lineage,
        "readable": run.readable,
    }
    if row is None:
        return {**base, "found": False}
    status = _status(row)
    human = status in _HUMAN_STATUSES
    value = effective_value(row)
    plain_value = str(row.get("plain_value") or "").strip()
    reason = str(
        (row.get("override_reasoning") if human else "")
        or row.get("reasoning") or row.get("notes") or ""
    ).strip()
    return {
        **base,
        "found": True,
        "row_id": _sid(row),
        "match": how,
        "value": value,
        # The display value only describes the AI default — never let it mask
        # a human's answer (decisionDisplay's rule).
        "plain_value": "" if human else plain_value,
        "status": status,
        "superseded": bool(row.get("superseded_by")),
        "by": str(row.get("decided_by") or "").strip(),
        "at": str(row.get("decided_at") or "").strip(),
        "reason": reason[:600],
    }


# ─── The core ──────────────────────────────────────────────────────


def history_for(row: dict, chain: list[ChainRun], others: list[ChainRun] | None = None,
                ) -> list[dict]:
    """The decision's value across the runs, OLDEST first, ending with the
    current run (``chain[0]``).

    Walks the chain newest → oldest, carrying the decision's candidate names:
    once it is found under an id in an older run, that id and the names that
    run's log knows for it become the first candidates for the run before.
    A run where it is not found contributes ``found: False`` and the names
    carry on unchanged. ``others`` (``scope=opp``) are runs outside the
    lineage, matched against every name the walk discovered, with no
    propagation of their own.
    """
    current = chain[0]
    cand = _Candidates.for_row(current.rows, _sid(row))
    entries = [{**_entry(current, row, "id"), "current": True}]
    all_names = {cand.exact, *cand.earlier}
    all_retired = set(cand.retired)
    for run in chain[1:]:
        if not run.readable:
            entries.append({**_entry(run, None, ""), "found": False})
            continue
        hit, how = _match(run.rows, cand)
        entries.append(_entry(run, hit, how))
        if hit is not None:
            cand = _Candidates.for_row(run.rows, _sid(hit)).merged(cand)
            all_names |= {cand.exact, *cand.earlier}
            all_retired |= set(cand.retired)
    for run in others or []:
        loose = _Candidates(exact=_sid(row), earlier=sorted(all_names - {_sid(row)}),
                            retired=sorted(all_retired))
        hit, how = _match(run.rows, loose)
        entries.append(_entry(run, hit, how))
    # Oldest first. Within the chain, chain order is the truth (a clone and
    # its source share a run id AND a date); other runs slot in by date.
    rank = {(r.workspace, r.run_id): len(chain) - i for i, r in enumerate(chain)}
    entries.sort(key=lambda e: (
        e.get("date") or "", e.get("run_id") or "", rank.get((e["workspace"], e["run_id"]), 0),
    ))
    return entries


def _clone_pairs(chain: list[ChainRun], others: list[ChainRun] | None = None,
                 ) -> dict[tuple[str, str], tuple[str, str]]:
    """``{clone key: source key}`` for every run known to be a clone of another."""
    pairs: dict[tuple[str, str], tuple[str, str]] = {}
    for i, run in enumerate(chain):
        if run.via == "cloned" and i + 1 < len(chain):
            pairs[(run.workspace, run.run_id)] = (chain[i + 1].workspace, chain[i + 1].run_id)
        elif run.clone_of:
            pairs[(run.workspace, run.run_id)] = run.clone_of
    for run in others or []:
        if run.clone_of:
            pairs[(run.workspace, run.run_id)] = run.clone_of
    return pairs


def collapse_clones(history: list[dict], chain: list[ChainRun],
                    others: list[ChainRun] | None = None) -> list[dict]:
    """Fold each clone's entry into its source's: one run, one entry.

    The surviving entry is the SOURCE's (its run is where the value was
    decided), with ``copied_to`` naming the clone's workspace and copy date,
    and ``current`` / ``in_lineage`` carried over from the clone. A clone whose
    value or status differs from its source keeps its own entry — that copy
    changed the decision, which is history worth showing.
    """
    pairs = _clone_pairs(chain, others)
    if not pairs:
        return history
    runs = {(r.workspace, r.run_id): r for r in [*chain, *(others or [])]}
    at = {(e["workspace"], e["run_id"]): i for i, e in enumerate(history)}
    out = [dict(e) for e in history]
    dropped: set[int] = set()
    # Oldest first, so a clone of a clone folds into the run it was copied from.
    for clone_key, src_key in sorted(pairs.items(), key=lambda kv: at.get(kv[0], -1)):
        ci, si = at.get(clone_key), at.get(src_key)
        if ci is None or si is None or ci in dropped:
            continue
        clone_e, src_e = out[ci], out[si]
        if clone_e.get("found") != src_e.get("found"):
            continue
        if clone_e.get("found") and (
            _norm(clone_e.get("value", "")) != _norm(src_e.get("value", ""))
            or clone_e.get("status") != src_e.get("status")
        ):
            continue
        clone_run = runs.get(clone_key)
        src_e["copied_to"] = [
            *src_e.get("copied_to", []),
            *clone_e.get("copied_to", []),
            {"workspace": clone_key[0],
             "date": clone_run.copied_date if clone_run else ""},
        ]
        if clone_e.get("current"):
            src_e["current"] = True
        src_e["in_lineage"] = bool(src_e.get("in_lineage") or clone_e.get("in_lineage"))
        dropped.add(ci)
    return [e for i, e in enumerate(out) if i not in dropped]


def origin_for(row: dict, history: list[dict], chain: list[ChainRun]) -> dict:
    """Where the current row's value came from, in one word.

    - ``human``: a person set it (``overridden`` / ``human-decided``);
    - ``new``: ACE decided it in THIS run — no earlier run of the chain has it;
    - ``decided``: ACE decided it in the run this one is a clone of (a clone
      and its source are one run, so the decision belongs to the source);
    - ``carried``: an earlier run had the same decision with the same value,
      under the same id — copied forward, not re-decided;
    - ``reaffirmed``: same value, but a re-run phase in the same workspace
      wrote it again (a new id, or a fork retired the old row);
    - ``changed``: the run before had it, with a different value.

    Leading clone hops are transparent: the clone's value is compared to its
    source, and when it matches, the SOURCE's own ancestry decides the kind.
    ``in_run`` is the run where the value was (re)decided — the head, or the
    clone's source; ``from_run`` is the run it is traced to: for ``carried`` /
    ``reaffirmed`` the EARLIEST run of an unbroken streak of the same value,
    for ``changed`` the run whose value was replaced, for ``new`` /
    ``decided`` the run itself. ``on_copy`` marks a ``changed`` that happened
    when the run was copied into this workspace.
    """
    status = _status(row)
    value = effective_value(row)
    if status in _HUMAN_STATUSES:
        return {
            "kind": "human",
            "status": status,
            "by": str(row.get("decided_by") or "").strip(),
            "at": str(row.get("decided_at") or "").strip(),
            "from_run": "",
            "previous_value": "",
        }
    lineage = [e for e in history if e.get("in_lineage")]
    by_run = {(e["workspace"], e["run_id"]): e for e in lineage}

    def found(i: int) -> dict | None:
        e = by_run.get((chain[i].workspace, chain[i].run_id))
        return e if e is not None and e.get("found") else None

    def here(kind: str, i: int, **extra) -> dict:
        return {
            "kind": kind,
            "from_run": chain[i].run_id if i else "",
            "from_workspace": chain[i].workspace if i else "",
            "in_run": chain[i].run_id,
            "in_workspace": chain[i].workspace,
            "previous_value": "",
            **extra,
        }

    # Skip the clone hops: while the run is a copy of the next one and the
    # copy kept the value, the next one is where the value really lives.
    h = 0
    while chain[h].via == "cloned" and h + 1 < len(chain):
        src = found(h + 1)
        if src is None:
            break
        if _norm(src["value"]) != _norm(value):
            return {
                **here("changed", h),
                "from_run": chain[h + 1].run_id,
                "from_workspace": chain[h + 1].workspace,
                "previous_value": src.get("plain_value") or src["value"],
                "on_copy": True,
            }
        h += 1

    fresh = "new" if h == 0 else "decided"
    if h + 1 >= len(chain):
        return here(fresh, h)
    parent = found(h + 1)
    if parent is None:
        return here(fresh, h)
    if _norm(parent["value"]) != _norm(value):
        return {
            **here("changed", h),
            "from_run": chain[h + 1].run_id,
            "from_workspace": chain[h + 1].workspace,
            "previous_value": parent.get("plain_value") or parent["value"],
        }
    # Same value: trace the streak back to the earliest run that had it.
    since = chain[h + 1]
    for i in range(h + 2, len(chain)):
        e = found(i)
        if e is None or _norm(e["value"]) != _norm(value):
            break
        since = chain[i]
    head_row = row
    if h:
        head_e = found(h)
        head_row = next(
            (r for r in chain[h].rows if _sid(r) == (head_e or {}).get("row_id")), row,
        )
    rewritten = parent.get("match") != "id" or bool(
        _fork_retired_predecessor(head_row, chain[h])
    )
    return {
        **here("reaffirmed" if rewritten else "carried", h),
        "from_run": since.run_id,
        "from_workspace": since.workspace,
    }


def _fork_retired_predecessor(row: dict, run: ChainRun) -> str:
    """The id of a row a fork retired in favour of ``row`` (it carries
    ``inherited_from_run`` and is superseded by this row), or ``""``."""
    rid = _sid(row)
    for pid in _predecessors(run.rows, rid):
        pred = next((r for r in run.rows if _sid(r) == pid), None)
        if pred is not None and pred.get("inherited_from_run"):
            return pid
    return ""


def trim_leading_absent(history: list[dict]) -> list[dict]:
    """Drop the runs from BEFORE the decision first existed.

    A history's leading ``found: False`` entries are runs older than the
    first one that has the decision — under ``scope=opp`` that can be a dozen
    runs from before the decision was ever written, which say nothing.
    Entries from the earliest run that has it onward are kept, including a
    not-found run between two found ones (a decision that disappeared and
    came back is real information). When no other run has it at all, the
    history is returned unchanged: "no earlier match" is itself the answer,
    and the runs that were searched are its evidence.
    """
    if not any(e.get("found") and not e.get("current") for e in history):
        return history
    # The earliest found entry — this run's own counts, so a decision only
    # NEWER runs of the opp share never loses this run's entry.
    first = next(i for i, e in enumerate(history) if e.get("found") or e.get("current"))
    return history[first:]


def build_lineage(chain: list[ChainRun], others: list[ChainRun] | None = None) -> dict:
    """Origins + histories for every LIVE row of ``chain[0]``.

    ``chain`` is newest first: ``[this run, its parent, …]``. Returns the
    viewer-independent core; see :func:`shape_for_viewer`.
    """
    if not chain:
        return {"chain": [], "origins": {}, "histories": {}, "counts": _zero_counts()}
    current = chain[0]
    origins: dict[str, dict] = {}
    histories: dict[str, list[dict]] = {}
    counts = _zero_counts()
    for row in current.rows:
        rid = _sid(row)
        if not rid or row.get("superseded_by") or rid in origins:
            continue
        hist = history_for(row, chain, others)
        origin = origin_for(row, hist, chain)
        origins[rid] = origin
        histories[rid] = trim_leading_absent(collapse_clones(hist, chain, others))
        counts[origin["kind"]] += 1
    return {
        "chain": [_chain_step(r) for r in chain],
        "origins": origins,
        "histories": histories,
        "counts": counts,
    }


def _zero_counts() -> dict[str, int]:
    return dict.fromkeys(ORIGIN_KINDS, 0)


def _chain_step(run: ChainRun) -> dict:
    return {
        "workspace": run.workspace,
        "opp": run.opp,
        "run_id": run.run_id,
        "via": run.via,
        "at_phase": run.at_phase,
        "date": run.date,
        "readable": run.readable,
        "decisions": len(run.rows),
        "copied_date": run.copied_date,
    }


# ─── Drive ─────────────────────────────────────────────────────────


def parent_of(state: dict, *, workspace: str, opp: str) -> tuple[str, str, str, str, str] | None:
    """``(workspace, opp, run_id, via, at_phase)`` of the run this one was made
    from, from its own run_state; ``None`` when it was built from nothing.

    A clone's ``clone.from`` wins: a clone copies the source run_state
    VERBATIM, so its ``forked_from`` still names the SOURCE's parent, which
    lives in the source workspace — the clone's real parent is the source run.
    """
    clone = state.get("clone")
    src = clone.get("from") if isinstance(clone, dict) else None
    if isinstance(src, dict) and src.get("run"):
        return (
            str(src.get("workspace") or workspace).strip(),
            str(src.get("opp") or opp).strip(),
            str(src.get("run")).strip(),
            "cloned",
            "",
        )
    seeded = str(state.get("seeded_from") or "").strip()
    forked = str(state.get("forked_from") or "").strip()
    if seeded or forked:
        return (
            workspace,
            opp,
            seeded or forked,
            "seeded" if seeded else "forked",
            str(state.get("forked_from_phase") or "").strip(),
        )
    return None


def _run_clone_source(workspace: str, opp: str, run_id: str):
    """A ``RunClone`` row naming this run as a clone target — the fallback for
    a clone whose run_state was never stamped with ``clone.from``."""
    try:
        from apps.workspaces.models import RunClone

        rc = (
            RunClone.objects.select_related("source_workspace")
            .filter(target_workspace__slug=workspace, opp_slug=opp, run_id=run_id,
                    status="done")
            .order_by("-created_at")
            .first()
        )
    except Exception:  # noqa: BLE001 — lineage is best-effort
        log.warning("lineage: RunClone lookup failed", exc_info=True)
        return None
    if rc is None:
        return None
    return (rc.source_workspace.slug, opp, run_id, "cloned", "")


def _clone_date(state: dict, workspace: str, opp: str, run_id: str) -> str:
    """The day a clone was copied: ``clone.at`` / ``clone.cloned_at`` when the
    stamp carries one, else the ``RunClone`` row's ``created_at``; ``""``."""
    clone = state.get("clone")
    if isinstance(clone, dict):
        for key in ("at", "cloned_at", "created"):
            got = run_date("", {"created": clone.get(key)}) if clone.get(key) else ""
            if got:
                return got
    try:
        from apps.workspaces.models import RunClone

        rc = (
            RunClone.objects.filter(target_workspace__slug=workspace, opp_slug=opp,
                                    run_id=run_id, status="done")
            .order_by("-created_at")
            .first()
        )
    except Exception:  # noqa: BLE001 — lineage is best-effort
        return ""
    return rc.created_at.date().isoformat() if rc is not None and rc.created_at else ""


_FOLDER = "application/vnd.google-apps.folder"


def _parse_yaml(text: str | None) -> dict:
    import yaml

    if not text:
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


class _RunReader:
    """Reads ``run_state.yaml`` + ``decisions.yaml`` of runs in any workspace.

    Round-trips are what make this slow, not bytes: the opp's ``runs/``
    listing is read once per workspace, a single run costs one listing of its
    folder plus its two files, and many runs (``scope=opp``) cost two batched
    ``find_in_folders`` queries plus one concurrent ``get_contents`` — the
    same fast paths the run list uses (``GoogleDriveClient``), with per-call
    fallbacks for a client that lacks them.
    """

    def __init__(self, drive_for_workspace):
        self._drive_for = drive_for_workspace
        self._clients: dict[str, object] = {}
        self._runs: dict[tuple[str, str], dict] = {}

    def _client(self, workspace: str):
        if workspace not in self._clients:
            self._clients[workspace] = self._drive_for(workspace)
        return self._clients[workspace]

    def _runs_children(self, workspace: str, opp: str):
        """``(drive, {run_id: DriveFile})`` for the opp's ``runs/`` folder."""
        from apps.opps.summary import _find_folder

        got = self._client(workspace)
        if got is None:
            return None, {}
        drive, root = got
        key = (workspace, opp)
        if key not in self._runs:
            opp_f = _find_folder(drive, root, opp)
            runs_f = _find_folder(drive, opp_f.id, "runs") if opp_f else None
            kids = drive.list_folder(runs_f.id) if runs_f else []
            self._runs[key] = {f.name: f for f in kids if f.mime_type == _FOLDER}
        return drive, self._runs[key]

    def list_runs(self, workspace: str, opp: str) -> list[str]:
        _drive, kids = self._runs_children(workspace, opp)
        return sorted(kids, reverse=True)

    def read(self, workspace: str, opp: str, run_id: str) -> tuple[dict, list[dict], bool]:
        """``(run_state, decision rows, readable)`` for one run."""
        try:
            drive, kids = self._runs_children(workspace, opp)
            run_f = kids.get(run_id)
            if drive is None or run_f is None:
                return {}, [], False
            files = {f.name: f for f in drive.list_folder(run_f.id)}
            wanted = [files[n] for n in ("run_state.yaml", "decisions.yaml") if n in files]
            texts = _contents(drive, [(f.id, f.mime_type) for f in wanted])
        except Exception:  # noqa: BLE001 — lineage is best-effort
            log.warning("lineage: reading %s/%s/%s failed", workspace, opp, run_id,
                        exc_info=True)
            return {}, [], False
        state_f, dec_f = files.get("run_state.yaml"), files.get("decisions.yaml")
        state = _parse_yaml(texts.get(state_f.id)) if state_f else {}
        rows = _rows_of(_parse_yaml(texts.get(dec_f.id)) if dec_f else {})
        return state, rows, True

    def read_many(self, workspace: str, opp: str, run_ids: list[str],
                  ) -> dict[str, tuple[dict, list[dict]]]:
        """``{run_id: (run_state, rows)}`` for every readable run of ``run_ids``."""
        try:
            drive, kids = self._runs_children(workspace, opp)
            folders = {rid: kids[rid].id for rid in run_ids if rid in kids}
            if drive is None or not folders:
                return {}
            states = _find_many(drive, list(folders.values()), "run_state.yaml")
            decs = _find_many(drive, list(folders.values()), "decisions.yaml")
            specs = [(f.id, f.mime_type) for f in [*states.values(), *decs.values()] if f]
            texts = _contents(drive, specs)
        except Exception:  # noqa: BLE001
            log.warning("lineage: bulk read of %s/%s failed", workspace, opp, exc_info=True)
            return {}
        out: dict[str, tuple[dict, list[dict]]] = {}
        for rid, fid in folders.items():
            state_f, dec_f = states.get(fid), decs.get(fid)
            state = _parse_yaml(texts.get(state_f.id)) if state_f else {}
            rows = _rows_of(_parse_yaml(texts.get(dec_f.id)) if dec_f else {})
            out[rid] = (state, rows)
        return out


def _rows_of(data: dict) -> list[dict]:
    raw = data.get("decisions")
    return [r for r in raw if isinstance(r, dict) and _sid(r)] if isinstance(raw, list) else []


def _find_many(drive, parent_ids: list[str], name: str) -> dict:
    finder = getattr(drive, "find_in_folders", None)
    if callable(finder):
        return finder(parent_ids, name)
    out = {}
    for pid in parent_ids:
        out[pid] = next((f for f in drive.list_folder(pid) if f.name == name), None)
    return out


def _contents(drive, specs: list[tuple[str, str]]) -> dict[str, str]:
    bulk = getattr(drive, "get_contents", None)
    if callable(bulk):
        return bulk(specs)
    out = {}
    for fid, mime in specs:
        try:
            out[fid] = drive.get_content(fid, mime).content or ""
        except Exception:  # noqa: BLE001
            log.warning("lineage: read %s failed", fid, exc_info=True)
    return out


def load_chain(drive_for_workspace, *, workspace: str, opp: str, run_id: str,
               max_hops: int = MAX_HOPS) -> list[ChainRun]:
    """The run and its ancestors, newest first.

    ``drive_for_workspace(slug)`` returns ``(drive_client, ace_root_folder_id)``
    for a workspace this deployment knows, else ``None`` — an unknown source
    workspace is still NAMED in the chain (``readable: False``) and the walk
    stops there.
    """
    reader = _RunReader(drive_for_workspace)
    chain: list[ChainRun] = []
    seen: set[tuple[str, str, str]] = set()
    cur: tuple[str, str, str] | None = (workspace, opp, run_id)
    while cur is not None and len(chain) <= max_hops and cur not in seen:
        seen.add(cur)
        ws, op, rid = cur
        state, rows, readable = reader.read(ws, op, rid)
        run = ChainRun(workspace=ws, opp=op, run_id=rid, rows=rows, readable=readable,
                       date=run_date(rid, state))
        chain.append(run)
        if not readable:
            break
        parent = parent_of(state, workspace=ws, opp=op) or _run_clone_source(ws, op, rid)
        if parent is None:
            break
        pws, pop, prid, via, at_phase = parent
        run.via, run.at_phase = via, at_phase
        if via == "cloned":
            run.clone_of = (pws, prid)
            run.copied_date = _clone_date(state, ws, op, rid)
        cur = (pws, pop, prid)
    return chain


def load_opp_runs(drive_for_workspace, chain: list[ChainRun], *,
                  limit: int = MAX_OPP_RUNS) -> list[ChainRun]:
    """Every other run of the opp, for ``scope=opp`` — newest ``limit`` of
    them per workspace, minus those already in the chain.

    "The opp" spans every workspace the chain passes through: a clone's
    history lives in its SOURCE workspace (the runs it was decided across),
    so a run in ``spark`` that was copied from ``dimagi-team`` reads the
    ``dimagi-team`` runs too. Each run's ``clone_of`` is filled in from its
    run_state, so a clone and its source fold into one history entry.
    """
    if not chain:
        return []
    reader = _RunReader(drive_for_workspace)
    in_chain = {(r.workspace, r.run_id) for r in chain}
    places = list(dict.fromkeys((r.workspace, r.opp) for r in chain if r.readable))
    out: list[ChainRun] = []
    for ws, opp in places:
        wanted = [
            rid for rid in reader.list_runs(ws, opp)[:limit] if (ws, rid) not in in_chain
        ]
        got = reader.read_many(ws, opp, wanted)
        for rid, (state, rows) in got.items():
            if not rows:
                continue
            run = ChainRun(workspace=ws, opp=opp, run_id=rid, rows=rows,
                           date=run_date(rid, state), in_lineage=False)
            parent = parent_of(state, workspace=ws, opp=opp)
            if parent is not None and parent[3] == "cloned":
                run.clone_of = (parent[0], parent[2])
                run.copied_date = _clone_date(state, ws, opp, rid)
            out.append(run)
    out.sort(key=lambda r: (r.date, r.run_id, r.workspace), reverse=True)
    return out


# ─── Viewer shaping ────────────────────────────────────────────────

_PHASE_STAGE = {
    "idea-to-design": "design",
    "design": "design",
    "scenarios-and-acceptance": "scenarios",
    "commcare-setup": "app build",
    "connect-setup": "Connect setup",
    "ocs-setup": "assistant setup",
    "qa-and-training": "QA and training",
    "synthetic-data-and-workflows": "demo",
    "solicitation-management": "solicitation",
    "execution-management": "execution",
    "closeout": "closeout",
}


def stage_label(phase: str) -> str:
    """The plain stage name a phase reads as (``commcare-setup`` → "app build")."""
    return _PHASE_STAGE.get(phase, phase.replace("-", " ") if phase else "")


def _person(value: str, *, member: bool) -> str:
    """A name for ``decided_by`` that never puts an email in front of a
    non-member: a known user's full name, else (members) the address, else
    "a reviewer"."""
    value = (value or "").strip()
    if not value:
        return ""
    if "@" not in value:
        return value
    try:
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(email__iexact=value).first()
        name = (user.get_full_name() or "").strip() if user is not None else ""
    except Exception:  # noqa: BLE001
        name = ""
    if name:
        return name
    return value if member else "a reviewer"


def shape_for_viewer(core: dict, *, member: bool, accessible: set[str],
                     script_name: str = "", plain: bool | None = None) -> dict:
    """Project the core for one viewer.

    - ``member`` — a signed-in member of the head run's workspace (any role).
      Echoed as ``viewer.is_member``; it is access, not presentation.
    - ``plain`` — draw the partner view. Defaults to ``not member``; the API
      passes ``True`` for a ``viewer``-role member too (a partner reviewer).
    - ``accessible`` — workspace slugs the viewer is a member of. A chain step
      in one of them carries ``workbench_url`` + ``summary_url``; any other is
      a label only (a clone's source in a workspace the viewer cannot open).
    - the plain view gets the strip and the badges in plain words: no run ids,
      workspaces or opp slugs, no per-decision history, no links.
    """
    if plain is None:
        plain = not member
    team = member and not plain
    steps = []
    for i, step in enumerate(core.get("chain") or []):
        linked = step["workspace"] in accessible and step.get("readable")
        path = f"{step['workspace']}/opps/{step['opp']}/runs/{step['run_id']}"
        base = f"{script_name}/w/{path}"
        summary = f"{script_name}/opps/{step['workspace']}/{step['opp']}/runs/{step['run_id']}"
        summary += "/summary"
        shaped = {
            "position": i,
            "via": step["via"],
            "at_phase": step["at_phase"] if team else "",
            "stage": stage_label(step["at_phase"]),
            "date": step["date"],
            "copied_date": step.get("copied_date", ""),
            "readable": step["readable"],
            "workbench_url": base if (team and linked) else None,
            "summary_url": summary if (team and linked) else None,
        }
        if team:
            shaped.update({
                "workspace": step["workspace"],
                "opp": step["opp"],
                "run_id": step["run_id"],
                "decisions": step.get("decisions", 0),
            })
        else:
            shaped.update({"workspace": None, "opp": None, "run_id": None, "decisions": None})
        steps.append(shaped)

    run_pos = {
        (s["workspace"], s["run_id"]): i for i, s in enumerate(core.get("chain") or [])
    }
    origins = {}
    chain_core = core.get("chain") or []
    for rid, o in (core.get("origins") or {}).items():
        pos = run_pos.get((o.get("from_workspace", ""), o.get("from_run", "")))
        in_pos = run_pos.get((o.get("in_workspace", ""), o.get("in_run", "")))
        origins[rid] = {
            "kind": o["kind"],
            "from_position": pos,
            "from_run": o.get("from_run") if team else None,
            "from_date": chain_core[pos]["date"] if pos is not None else "",
            # Where the value was (re)decided: this run (0), or the run a
            # clone was copied from.
            "in_position": in_pos,
            "in_run": o.get("in_run") if team else None,
            "in_date": chain_core[in_pos]["date"] if in_pos is not None else "",
            "on_copy": bool(o.get("on_copy")),
            "previous_value": o.get("previous_value", "") if team else "",
            "by": _person(o.get("by", ""), member=team),
            "at": o.get("at", ""),
        }

    histories: dict[str, list[dict]] = {}
    if team:
        for rid, hist in (core.get("histories") or {}).items():
            histories[rid] = [
                {
                    **e,
                    "by": _person(e.get("by", ""), member=True),
                    "linked": e.get("workspace") in accessible,
                }
                for e in hist
            ]

    return {
        "schema_version": 1,
        "scope": core.get("scope", "lineage"),
        "chain": steps,
        "origins": origins,
        "counts": core.get("counts") or _zero_counts(),
        "histories": histories,
        "viewer": {"is_member": member, "plain": plain},
    }
