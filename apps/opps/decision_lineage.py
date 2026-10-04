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
  and its **origin** (one of ``new`` / ``carried`` / ``changed`` /
  ``reaffirmed`` / ``human``).
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

ORIGIN_KINDS = ("new", "carried", "changed", "reaffirmed", "human")

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
    entries = [_entry(current, row, "id")]
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


def origin_for(row: dict, history: list[dict], chain: list[ChainRun]) -> dict:
    """Where the current row's value came from, in one word.

    - ``human``: a person set it (``overridden`` / ``human-decided``);
    - ``new``: no earlier run of the chain has it (or there is no chain);
    - ``carried``: the parent run had the same decision with the same value,
      under the same id — copied forward, not re-decided;
    - ``reaffirmed``: same value, but this run wrote it again (a re-run phase
      re-emitted it under a new id, or a fork retired the old row);
    - ``changed``: the parent run had it, with a different value.

    ``from_run`` is the run the value is traced to: for ``carried`` /
    ``reaffirmed`` the EARLIEST run in an unbroken streak of the same value,
    for ``changed`` the parent (whose value was replaced).
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
    if len(chain) < 2:
        return {"kind": "new", "from_run": "", "previous_value": ""}
    parent = by_run.get((chain[1].workspace, chain[1].run_id))
    if parent is None or not parent.get("found"):
        return {"kind": "new", "from_run": "", "previous_value": ""}
    if _norm(parent["value"]) != _norm(value):
        return {
            "kind": "changed",
            "from_run": chain[1].run_id,
            "from_workspace": chain[1].workspace,
            "previous_value": parent.get("plain_value") or parent["value"],
        }
    # Same value: trace the streak back to the earliest run that had it.
    since = chain[1]
    for run in chain[2:]:
        e = by_run.get((run.workspace, run.run_id))
        if e is None or not e.get("found") or _norm(e["value"]) != _norm(value):
            break
        since = run
    rewritten = parent.get("match") != "id" or bool(_fork_retired_predecessor(row, chain[0]))
    return {
        "kind": "reaffirmed" if rewritten else "carried",
        "from_run": since.run_id,
        "from_workspace": since.workspace,
        "previous_value": "",
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
        histories[rid] = hist
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
        cur = (pws, pop, prid)
    return chain


def load_opp_runs(drive_for_workspace, chain: list[ChainRun], *,
                  limit: int = MAX_OPP_RUNS) -> list[ChainRun]:
    """Every other run of the current run's opp (its own workspace), for
    ``scope=opp`` — newest ``limit`` of them, minus those already in the chain."""
    if not chain:
        return []
    reader = _RunReader(drive_for_workspace)
    head = chain[0]
    in_chain = {(r.workspace, r.run_id) for r in chain}
    wanted = [
        rid for rid in reader.list_runs(head.workspace, head.opp)[:limit]
        if (head.workspace, rid) not in in_chain
    ]
    got = reader.read_many(head.workspace, head.opp, wanted)
    return [
        ChainRun(workspace=head.workspace, opp=head.opp, run_id=rid, rows=rows,
                 date=run_date(rid, state), in_lineage=False)
        for rid, (state, rows) in sorted(got.items(), reverse=True)
        if rows
    ]


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
                     script_name: str = "") -> dict:
    """Project the core for one viewer.

    - ``accessible`` — workspace slugs the viewer is a member of. A chain step
      in one of them carries ``workbench_url`` + ``summary_url``; any other is
      a label only (a clone's source in a workspace the viewer cannot open).
    - a non-member (``member=False``) gets the strip and the badges in plain
      words: no run ids, workspaces or opp slugs, no per-decision history.
    """
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
            "at_phase": step["at_phase"] if member else "",
            "stage": stage_label(step["at_phase"]),
            "date": step["date"],
            "readable": step["readable"],
            "workbench_url": base if (member and linked) else None,
            "summary_url": summary if (member and linked) else None,
        }
        if member:
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
    for rid, o in (core.get("origins") or {}).items():
        pos = run_pos.get((o.get("from_workspace", ""), o.get("from_run", "")))
        origins[rid] = {
            "kind": o["kind"],
            "from_position": pos,
            "from_run": o.get("from_run") if member else None,
            "from_date": core["chain"][pos]["date"] if pos is not None else "",
            "previous_value": o.get("previous_value", "") if member else "",
            "by": _person(o.get("by", ""), member=member),
            "at": o.get("at", ""),
        }

    histories: dict[str, list[dict]] = {}
    if member:
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
        "viewer": {"is_member": member},
    }
