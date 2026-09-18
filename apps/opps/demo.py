"""Demo Player payload — a saved run, rendered as an ordered set of acts.

The Workbench is built for ACE-team QA and the public summary page for a
partner who wants the deliverables. Neither tells the *story* of a run to a
room. This module derives that story from data every run already has.

Design: docs/specs/2026-09-17-ace-demo-player-design.md

Two rules govern everything here:

**The honesty rule.** The player never renders a value it cannot source from
the run. When an act's data is missing the act is returned unavailable with a
reason, never filled in. The player's whole value is that it is evidence; one
fabricated number destroys it.

That rule is why there are three timing modes rather than two. ACE reliably
stamps PHASE boundaries in run_state.yaml but almost never per-STEP ones — a
real 2026-07 run carried a measured span on every phase and a timestamp on 0
of its 48 steps — so a player that only understood step times would fall back
to "no clock at all" on essentially every finished run, and one that spread
steps evenly across a phase and printed the result as a step time would be
inventing measurements. So:

* ``measured`` — steps carry their own timestamps. Step times are real.
* ``phase``    — only phase boundaries are stamped. The run clock and the
  per-phase ledger are real; steps are POSITIONED inside their phase for
  layout, and the player must not print a per-step time it did not measure.
* ``ordinal``  — nothing is stamped. Sequence only, no clock anywhere.

**No token or cost readout.** Elapsed wall time is the only measure of effort
the player reports. This is deliberate — a token count is not a unit an
audience converts into meaning, and the funder audience is frequently an AI
company, to whom a per-phase token ledger discloses our own cost structure.
Do not add one. See the spec section of the same name.

Derived only: no new ORM tables, no Drive reads of its own. It consumes the
same rich snapshot payload the Workbench renders, so it inherits the snapshot
cache and the freshness overlays for free.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Statuses that mean "this step did not run", and so contributes no event.
_INERT_STATUSES = frozenset({"pending", "skipped"})

# Statuses that mean "this step ran and did not succeed".
_FAILED_STATUSES = frozenset({"qa-failed", "judge-fail", "error"})


# --------------------------------------------------------------------------- #
# time helpers
# --------------------------------------------------------------------------- #
def _parse_iso(value: Any) -> dt.datetime | None:
    """Parse a snapshot timestamp into an aware UTC datetime, or None.

    Accepts both shapes the read path can produce: an ISO-8601 string from the
    serializers, and a ``datetime`` that PyYAML auto-parsed out of run_state
    and that survived the snapshot cache. Anything unparseable returns None —
    the caller degrades to ordinal sequencing rather than guessing.
    """
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _offset_seconds(moment: dt.datetime | None, origin: dt.datetime | None) -> float | None:
    """Seconds from ``origin`` to ``moment``, or None when either is missing.

    Negative offsets are clamped to 0: a step stamped microseconds before the
    run header is a clock-skew artifact, not a step that ran before the run
    started, and a negative offset would render as an event off the left edge.
    """
    if moment is None or origin is None:
        return None
    return max(0.0, (moment - origin).total_seconds())


# --------------------------------------------------------------------------- #
# timeline
# --------------------------------------------------------------------------- #
def _live_steps(steps: list[dict]) -> list[dict]:
    """Steps that actually ran, in execution order."""
    live = [s for s in steps if (s.get("status") or "pending") not in _INERT_STATUSES]
    return sorted(live, key=lambda s: (s.get("ordinal") or 0, s.get("skill_name") or ""))


def _phase_spans(run: dict) -> dict[str, tuple[dt.datetime | None, dt.datetime | None]]:
    """``{phase: (started_at, completed_at)}`` from the run's phase_timings."""
    raw = run.get("phase_timings")
    if not isinstance(raw, dict):
        return {}
    spans: dict[str, tuple[dt.datetime | None, dt.datetime | None]] = {}
    for name, block in raw.items():
        if not isinstance(block, dict):
            continue
        start = _parse_iso(block.get("started_at"))
        end = _parse_iso(block.get("completed_at"))
        if start or end:
            spans[str(name)] = (start, end)
    return spans


def _run_origin(
    steps: list[dict],
    run: dict,
    spans: dict[str, tuple[dt.datetime | None, dt.datetime | None]],
) -> dt.datetime | None:
    """The instant the run's clock starts.

    Prefers the earliest measured moment in the run's own work — step stamps
    first, then phase stamps — over the run header. A run resumed after an
    interruption carries a header timestamp from its first attempt, which
    would stretch the timeline across the dead hours in between.
    """
    starts = [ts for ts in (_parse_iso(s.get("started_at")) for s in steps) if ts is not None]
    if starts:
        return min(starts)
    phase_starts = [t for pair in spans.values() for t in pair if t is not None]
    if phase_starts:
        return min(phase_starts)
    return _parse_iso(run.get("started_at"))


def _run_end(
    steps: list[dict],
    run: dict,
    spans: dict[str, tuple[dt.datetime | None, dt.datetime | None]],
) -> dt.datetime | None:
    ends = [ts for ts in (_parse_iso(s.get("completed_at")) for s in steps) if ts is not None]
    if ends:
        return max(ends)
    phase_ends = [t for pair in spans.values() for t in pair if t is not None]
    if phase_ends:
        return max(phase_ends)
    return _parse_iso(run.get("completed_at"))


def build_timeline(snapshot: dict) -> dict:
    """Derive the Time Machine's event stream from a rich snapshot payload.

    Returns ``{timing_source, origin, wall_seconds, events}``. Every event
    carries a ``seq`` (always orderable) and a ``t`` in seconds from the run
    origin (null when that step carries no usable timestamp).
    """
    run = snapshot.get("current_run") or {}
    steps = _live_steps(run.get("steps") or [])
    spans = _phase_spans(run)
    origin = _run_origin(steps, run, spans)
    end = _run_end(steps, run, spans)

    step_measured = origin is not None and any(
        _parse_iso(s.get("completed_at")) is not None for s in steps
    )
    phase_measured = origin is not None and bool(spans)
    if step_measured:
        timing_source = "measured"
    elif phase_measured:
        timing_source = "phase"
    else:
        timing_source = "ordinal"

    # In phase mode a step's offset is INTERPOLATED across its phase's span so
    # the band and the playhead have somewhere to put it. That is layout, not
    # measurement: the event carries ``t_estimated: true`` and the player must
    # not print it as a step time.
    ordinals: dict[str, list[dict]] = {}
    for step in steps:
        ordinals.setdefault(step.get("phase") or "", []).append(step)

    def interpolated(step: dict) -> float | None:
        phase = step.get("phase") or ""
        span = spans.get(phase)
        if not span or origin is None:
            return None
        start, finish = span
        start = start or finish
        finish = finish or start
        if start is None or finish is None:
            return None
        members = ordinals.get(phase) or [step]
        index = members.index(step) if step in members else 0
        share = (index + 1) / len(members)
        seconds = (finish - start).total_seconds() * share
        return _offset_seconds(start + dt.timedelta(seconds=seconds), origin)

    events: list[dict] = []
    seq = 0
    seen_phases: set[str] = set()

    for step in steps:
        phase = step.get("phase") or ""
        started = _parse_iso(step.get("started_at"))
        completed = _parse_iso(step.get("completed_at"))
        estimated = False

        if phase and phase not in seen_phases:
            seen_phases.add(phase)
            span = spans.get(phase)
            phase_t = _offset_seconds(started or completed, origin)
            if phase_t is None and span:
                phase_t = _offset_seconds(span[0] or span[1], origin)
            events.append({
                "seq": seq,
                "t": phase_t,
                "kind": "phase_start",
                "phase": phase,
                "phase_display": step.get("phase_display") or phase,
                "t_estimated": False,
            })
            seq += 1

        start_t = _offset_seconds(started, origin)
        if start_t is None:
            start_t = interpolated(step)
            estimated = start_t is not None
        events.append({
            "seq": seq,
            "t": start_t,
            "kind": "step_start",
            "phase": phase,
            "phase_display": step.get("phase_display") or phase,
            "skill": step.get("skill_name"),
            "skill_display": step.get("display_name") or step.get("skill_name"),
            "t_estimated": estimated,
        })
        seq += 1

        duration = None
        if started is not None and completed is not None:
            duration = max(0.0, (completed - started).total_seconds())

        end_t = _offset_seconds(completed, origin)
        end_estimated = False
        if end_t is None:
            end_t = interpolated(step)
            end_estimated = end_t is not None
        events.append({
            "seq": seq,
            "t": end_t,
            "t_estimated": end_estimated,
            "kind": "step_end",
            "phase": phase,
            "phase_display": step.get("phase_display") or phase,
            "skill": step.get("skill_name"),
            "skill_display": step.get("display_name") or step.get("skill_name"),
            "status": step.get("status"),
            "duration_seconds": duration,
            "artifacts": [
                {"name": a.get("name"), "url": a.get("drive_web_link") or a.get("url")}
                for a in (step.get("artifacts") or [])
            ],
            "judge": step.get("judge"),
            "qa_result": step.get("qa_result"),
            "error": step.get("error"),
        })
        seq += 1

    wall_seconds = None
    if origin is not None and end is not None:
        wall_seconds = max(0.0, (end - origin).total_seconds())

    return {
        "timing_source": timing_source,
        "origin": origin.isoformat().replace("+00:00", "Z") if origin else None,
        "wall_seconds": wall_seconds,
        "events": events,
    }


# --------------------------------------------------------------------------- #
# time ledger
# --------------------------------------------------------------------------- #
def build_time_ledger(snapshot: dict) -> dict:
    """Wall time per phase, drilling to skill.

    Phase duration is measured span (first start → last completion within the
    phase), not the sum of its skills': the gaps between skills are real
    elapsed time and summing would under-report them. ``active_seconds`` keeps
    the summed figure alongside so the player can show both without either
    being mistaken for the other.
    """
    run = snapshot.get("current_run") or {}
    steps = _live_steps(run.get("steps") or [])
    spans = _phase_spans(run)

    order: list[str] = []
    grouped: dict[str, list[dict]] = {}
    for step in steps:
        phase = step.get("phase") or ""
        if phase not in grouped:
            grouped[phase] = []
            order.append(phase)
        grouped[phase].append(step)

    phases = []
    for phase in order:
        members = grouped[phase]
        starts = [t for t in (_parse_iso(s.get("started_at")) for s in members) if t]
        ends = [t for t in (_parse_iso(s.get("completed_at")) for s in members) if t]
        span = None
        if starts and ends:
            span = max(0.0, (max(ends) - min(starts)).total_seconds())
        else:
            # No step in this phase carried a stamp — fall back to the phase's
            # own measured boundaries, which is the clock a real run actually
            # records. Still a MEASURED value, just read one level up.
            phase_start, phase_end = spans.get(phase, (None, None))
            if phase_start and phase_end:
                span = max(0.0, (phase_end - phase_start).total_seconds())

        skills = []
        active = 0.0
        for s in members:
            st, cp = _parse_iso(s.get("started_at")), _parse_iso(s.get("completed_at"))
            dur = max(0.0, (cp - st).total_seconds()) if st and cp else None
            if dur is not None:
                active += dur
            skills.append({
                "skill": s.get("skill_name"),
                "skill_display": s.get("display_name") or s.get("skill_name"),
                "status": s.get("status"),
                "seconds": dur,
            })

        phases.append({
            "phase": phase,
            "phase_display": members[0].get("phase_display") or phase,
            "seconds": span,
            # None, never a guess: without per-step stamps there is no honest
            # "time actually working" figure to report for this phase.
            "active_seconds": active if active else None,
            "skill_count": len(members),
            "skills": skills,
        })

    timeline = build_timeline(snapshot)
    return {
        "wall_seconds": timeline["wall_seconds"],
        "timing_source": timeline["timing_source"],
        "phases": phases,
    }


# --------------------------------------------------------------------------- #
# the gate that failed
# --------------------------------------------------------------------------- #
def _judge_failed(judge: Any) -> bool:
    return isinstance(judge, dict) and judge.get("passed") is False


def _qa_failed(qa: Any) -> bool:
    return isinstance(qa, dict) and (
        qa.get("verdict") == "fail" or qa.get("passed") is False
    )


def build_gates(snapshot: dict) -> list[dict]:
    """Every step whose own QA or judge verdict did not pass.

    This act exists because a demo that only shows success gets discounted by
    exactly the audiences worth convincing. Showing the system catching its own
    bad work is the argument that it is engineered rather than prompted — so
    these are surfaced, never filtered.
    """
    run = snapshot.get("current_run") or {}
    gates = []
    for step in _live_steps(run.get("steps") or []):
        judge, qa = step.get("judge"), step.get("qa_result")
        status = step.get("status") or ""
        if not (_judge_failed(judge) or _qa_failed(qa) or status in _FAILED_STATUSES):
            continue
        gates.append({
            "skill": step.get("skill_name"),
            "skill_display": step.get("display_name") or step.get("skill_name"),
            "phase": step.get("phase"),
            "phase_display": step.get("phase_display") or step.get("phase"),
            "ordinal": step.get("ordinal"),
            "status": status,
            "judge": judge,
            "qa_result": qa,
            "error": step.get("error"),
        })
    return gates


# --------------------------------------------------------------------------- #
# decisions
# --------------------------------------------------------------------------- #
def build_decisions(snapshot: dict) -> dict:
    """The run's decision rows, split by whether a human moved them.

    ``overridden`` is the interesting half — it is the visible evidence that a
    person reviewed the agent's default and changed it.
    """
    run = snapshot.get("current_run") or {}
    rows = [d for d in (run.get("decisions") or []) if isinstance(d, dict)]
    overridden = [d for d in rows if d.get("status") == "overridden"]
    return {
        "total": len(rows),
        "overridden_count": len(overridden),
        "rows": rows,
    }


# --------------------------------------------------------------------------- #
# acts
# --------------------------------------------------------------------------- #
def build_acts(snapshot: dict) -> tuple[list[dict], dict]:
    """Compute the act list and the capability map for one run.

    An act is returned whether or not it is available — an unavailable act
    carries the reason, so the player can say *why* a thin run gets a short
    demo instead of silently rendering fewer beats.
    """
    timeline = build_timeline(snapshot)
    ledger = build_time_ledger(snapshot)
    gates = build_gates(snapshot)
    decisions = build_decisions(snapshot)

    has_events = bool(timeline["events"])
    # Phase-level stamps are a real clock, so the ledger works on them. Only a
    # run with no stamps at all loses the act.
    measured = timeline["timing_source"] in ("measured", "phase")

    acts = [
        {
            "id": "timeline",
            "title": "The run",
            "available": has_events,
            "unavailable_reason": None if has_events else "This run has no completed steps yet.",
            "data": timeline,
        },
        {
            "id": "time_ledger",
            "title": "Where the time went",
            "available": has_events and measured,
            "unavailable_reason": (
                None
                if (has_events and measured)
                else "This run recorded no timestamps, so elapsed time can't be measured."
            ),
            "data": ledger,
        },
        {
            "id": "gates",
            "title": "What it caught",
            "available": bool(gates),
            "unavailable_reason": (
                None if gates else "No step in this run failed its own QA or judge."
            ),
            "data": {"gates": gates},
        },
        {
            "id": "decisions",
            "title": "What it decided",
            "available": decisions["total"] > 0,
            "unavailable_reason": (
                None if decisions["total"] else "This run wrote no decisions log."
            ),
            "data": decisions,
        },
    ]

    capabilities = {a["id"]: a["available"] for a in acts}
    return acts, capabilities


def build_demo_payload(snapshot: dict, *, run_id: str | None = None) -> dict:
    """Assemble the full Demo Player payload from a rich snapshot dict."""
    run = snapshot.get("current_run") or {}
    opp = snapshot.get("opp") or {}
    acts, capabilities = build_acts(snapshot)
    timeline = next(a["data"] for a in acts if a["id"] == "timeline")

    return {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "opp_slug": snapshot.get("slug") or opp.get("slug"),
            "opp_title": snapshot.get("title") or opp.get("display_name") or snapshot.get("slug"),
            "run_id": run.get("run_id") or run_id,
            "status": run.get("status"),
            "started_at": run.get("started_at"),
            "completed_at": run.get("completed_at"),
            "wall_seconds": timeline["wall_seconds"],
            "step_count": len(_live_steps(run.get("steps") or [])),
        },
        "timing_source": timeline["timing_source"],
        "capabilities": capabilities,
        "acts": acts,
    }
