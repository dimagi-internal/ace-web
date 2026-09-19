"""Compare two runs of one opp — what the later run did differently.

The obvious comparison is scores, and it tells the wrong story. On
``hh-poverty-targeting`` the run after an outside review (2026-07-28) passed
FEWER of its own checks than the run before it (2026-07-22): 24 passes against
31, with six new warns and two new fails. The work did not get worse — the
review showed ACE's graders were too lenient, and they got stricter. A table
built around score deltas would put a red arrow on the better run.

So this leads with what is NEW:

  * decisions the later run made that the earlier one never considered
    (21 on that pair — which fields are required, which outcomes capture GPS,
    whether the budget is plausible, …),
  * checks the later run ran that the earlier one did not,
  * decisions both runs made but answered differently,

and keeps the step-by-step verdicts as a plain side-by-side for anyone who
wants them, deliberately without better/worse framing.

It also says WHAT changed and never WHY. Between two runs ACE changes for many
reasons at once — a reviewer's comments, unrelated skill work, a newer plugin —
and nothing in the run data records which change caused which difference.

Pure functions over two rich snapshot dicts (``serialize_opp_snapshot``
output), so it rides the Workbench's snapshot cache and needs no Drive reads of
its own.
"""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1

# A step that never ran is not something the run "did".
_INERT = frozenset({"pending", "skipped", ""})


def _run(snapshot: dict) -> dict:
    return snapshot.get("current_run") or {}


def _phase_meta(*snapshots: dict) -> dict[str, dict]:
    """``{phase name: {display, ordinal}}`` from the plugin's phase registry."""
    out: dict[str, dict] = {}
    for snap in snapshots:
        for p in snap.get("phases") or []:
            if isinstance(p, dict) and p.get("name") and p["name"] not in out:
                out[p["name"]] = {
                    "display": p.get("display_name") or p["name"],
                    "ordinal": p.get("ordinal"),
                }
    return out


def _ran(step: dict) -> bool:
    return str(step.get("status") or "").lower() not in _INERT


def _verdict(step: dict | None) -> dict | None:
    """What a step's own review said, as plain facts — no better/worse."""
    if step is None:
        return None
    judge = step.get("judge") or {}
    qa = step.get("qa_result") or {}
    status = str(step.get("status") or "")
    if status in ("judge-fail", "qa-failed", "error") or judge.get("passed") is False or (
        qa.get("verdict") == "fail"
    ):
        label = "did not pass"
    elif not _ran(step):
        label = "did not run"
    elif judge.get("passed") is True or qa.get("verdict") == "pass" or status == "complete":
        label = "passed"
    else:
        label = status or "unknown"
    score = judge.get("score_pct")
    if score is None:
        score = judge.get("score")
    return {"label": label, "status": status, "score": score}


def _answer(decision: dict) -> Any:
    """What the run settled on: a human override if there was one."""
    override = decision.get("override")
    return override if override not in (None, "") else decision.get("ai_default")


def _same(a: Any, b: Any) -> bool:
    """Equal once case, spacing and trailing punctuation are ignored.

    On the real before/after pair, "weekly" -> "Weekly" was one of 22
    "changed" answers. A rewording of nothing is not a change worth a row.
    """
    def norm(v: Any) -> str:
        return " ".join(str(v).split()).casefold().rstrip(" .;,")

    return norm(a) == norm(b)


def _decision_row(d: dict, phases: dict[str, dict]) -> dict:
    phase = d.get("phase") or ""
    return {
        "id": d.get("id"),
        "phase": phase,
        "phase_display": (phases.get(phase) or {}).get("display") or phase,
        "skill": d.get("skill"),
        "question": d.get("question") or "",
        "answer": _answer(d),
        "overridden": d.get("status") == "overridden",
    }


def _step_row(s: dict, phases: dict[str, dict]) -> dict:
    phase = s.get("phase") or ""
    return {
        "skill": s.get("skill_name"),
        "display_name": s.get("display_name") or s.get("skill_name"),
        "phase": phase,
        "phase_display": s.get("phase_display") or (phases.get(phase) or {}).get("display")
        or phase,
    }


def _phase_order(phases: dict[str, dict]):
    def key(row: dict) -> tuple:
        ordinal = (phases.get(row.get("phase") or "") or {}).get("ordinal")
        return (ordinal if isinstance(ordinal, int) else 999, row.get("phase") or "")

    return key


def _header(snapshot: dict) -> dict:
    run = _run(snapshot)
    steps = run.get("steps") or []
    return {
        "run_id": run.get("run_id"),
        "started_at": run.get("started_at"),
        "completed_at": run.get("completed_at"),
        "steps_run": sum(1 for s in steps if isinstance(s, dict) and _ran(s)),
        "decision_count": len(run.get("decisions") or []),
    }


def build_run_compare(base: dict, head: dict) -> dict:
    """``base`` is the earlier run, ``head`` the later one."""
    phases = _phase_meta(base, head)
    order = _phase_order(phases)

    base_decisions = {d.get("id"): d for d in _run(base).get("decisions") or [] if d.get("id")}
    head_decisions = {d.get("id"): d for d in _run(head).get("decisions") or [] if d.get("id")}

    new_decisions = [
        _decision_row(d, phases) for k, d in head_decisions.items() if k not in base_decisions
    ]
    dropped_decisions = [
        _decision_row(d, phases) for k, d in base_decisions.items() if k not in head_decisions
    ]
    changed_decisions = []
    for k, hd in head_decisions.items():
        bd = base_decisions.get(k)
        if bd is None:
            continue
        before, after = _answer(bd), _answer(hd)
        if not _same(before, after):
            row = _decision_row(hd, phases)
            row["before"] = before
            row["after"] = after
            changed_decisions.append(row)

    base_steps = {s.get("skill_name"): s for s in _run(base).get("steps") or []
                  if isinstance(s, dict) and s.get("skill_name")}
    head_steps = {s.get("skill_name"): s for s in _run(head).get("steps") or []
                  if isinstance(s, dict) and s.get("skill_name")}

    def ran_in(steps: dict, skill: str) -> bool:
        return skill in steps and _ran(steps[skill])

    new_steps = [
        _step_row(s, phases) for k, s in head_steps.items() if _ran(s) and not ran_in(base_steps, k)
    ]
    dropped_steps = [
        _step_row(s, phases) for k, s in base_steps.items() if _ran(s) and not ran_in(head_steps, k)
    ]

    rows = []
    for skill in set(base_steps) | set(head_steps):
        b, h = base_steps.get(skill), head_steps.get(skill)
        either = h or b or {}
        vb, vh = _verdict(b), _verdict(h)
        rows.append({
            **_step_row(either, phases),
            "ordinal": either.get("ordinal"),
            "base": vb,
            "head": vh,
            "changed": (vb or {}).get("label") != (vh or {}).get("label"),
        })
    rows.sort(key=lambda r: (order(r), r.get("ordinal") or 0, r.get("skill") or ""))

    for group in (new_decisions, dropped_decisions, changed_decisions, new_steps, dropped_steps):
        group.sort(key=order)

    return {
        "schema_version": SCHEMA_VERSION,
        "opp_slug": head.get("slug") or (head.get("opp") or {}).get("slug"),
        "opp_title": (head.get("opp") or {}).get("display_name") or head.get("title"),
        "base": _header(base),
        "head": _header(head),
        "new_decisions": new_decisions,
        "changed_decisions": changed_decisions,
        "dropped_decisions": dropped_decisions,
        "new_steps": new_steps,
        "dropped_steps": dropped_steps,
        "steps": rows,
    }
