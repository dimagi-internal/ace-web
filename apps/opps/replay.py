"""Run replay payload — a saved run, rendered as a stepped-through beat stream.

The Workbench shows a run's FINAL state. This module derives the same run as
a sequence of beats — entering a phase, starting a skill, finishing one — so
the Phases screen can replay it: filling in as it goes, steppable one beat at
a time, so anyone can watch the system work rather than read its output.

It is deliberately a mode of the real Workbench rather than a separate
presentation surface. A bespoke replay would be a second rendering of phases,
skills and verdicts that drifts from the one people actually use, and showing
the real tool is more convincing than showing a picture of it.

Design: docs/specs/2026-09-17-ace-demo-player-design.md (built as
Workbench replay rather than a standalone player — see that spec's addendum)

Two rules govern everything here:

**The honesty rule.** The player never renders a value it cannot source from
the run. When an act's data is missing the act is returned unavailable with a
reason, never filled in. The replay's whole value is that it is evidence; one
fabricated number destroys it.

That rule is why there are three timing modes rather than two. ACE reliably
stamps PHASE boundaries in run_state.yaml but almost never per-STEP ones — a
real 2026-07 run carried a measured span on every phase and a timestamp on 0
of its 48 steps — so a replay that only understood step times would fall back
to "no clock at all" on essentially every finished run, and one that spread
steps evenly across a phase and printed the result as a step time would be
inventing measurements. So:

* ``measured`` — steps carry their own timestamps. Step times are real.
* ``phase``    — only phase boundaries are stamped. The run clock and the
  per-phase ledger are real; steps are POSITIONED inside their phase for
  layout, and the UI must not print a per-step time it did not measure.
* ``ordinal``  — nothing is stamped. Sequence only, no clock anywhere.

**No token or cost readout.** Elapsed wall time is the only measure of effort
the replay reports. This is deliberate — a token count is not a unit an
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
import re
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2

# Statuses that mean "this step did not run", and so contributes no event.
_INERT_STATUSES = frozenset({"pending", "skipped"})



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
            "preview_text": step.get("preview_text"),
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
# ladder — the run's whole plan, phase by phase
# --------------------------------------------------------------------------- #
def build_ladder(snapshot: dict) -> list[dict]:
    """Every phase and every skill in the run, in order, whether or not it ran.

    The Workbench shows the plan; so does the replay. A step that never ran is
    present and marked ``ran: false`` so the audience can see what was still
    ahead at any point in the replay, instead of steps appearing from nowhere.

    Phase ordinals come from the plugin's own phase registry (the snapshot's
    ``phases``), so the ladder numbers phases the way every other ACE surface
    does rather than inventing its own sequence.
    """
    run = snapshot.get("current_run") or {}
    all_steps = run.get("steps") or []
    registry = {
        p.get("name"): p for p in (snapshot.get("phases") or []) if isinstance(p, dict)
    }

    order: list[str] = []
    grouped: dict[str, list[dict]] = {}
    for step in sorted(all_steps, key=lambda s: (s.get("ordinal") or 0, s.get("skill_name") or "")):
        phase = step.get("phase") or ""
        if phase not in grouped:
            grouped[phase] = []
            order.append(phase)
        grouped[phase].append(step)

    def phase_sort_key(name: str) -> tuple[int, int]:
        meta = registry.get(name) or {}
        ordinal = meta.get("ordinal")
        return (0, ordinal) if isinstance(ordinal, int) else (1, order.index(name))

    ladder = []
    for phase in sorted(order, key=phase_sort_key):
        members = grouped[phase]
        meta = registry.get(phase) or {}
        ladder.append({
            "phase": phase,
            "phase_display": (
                meta.get("display_name") or members[0].get("phase_display") or phase
            ),
            "ordinal": meta.get("ordinal"),
            "steps": [
                {
                    "skill": s.get("skill_name"),
                    "skill_display": s.get("display_name") or s.get("skill_name"),
                    "ordinal": s.get("ordinal"),
                    "status": s.get("status"),
                    "ran": (s.get("status") or "pending") not in _INERT_STATUSES,
                    "has_judge": s.get("has_judge"),
                    "judge": s.get("judge"),
                    "qa_result": s.get("qa_result"),
                    "preview_text": s.get("preview_text"),
                    "error": s.get("error"),
                    "artifacts": [
                        {"name": a.get("name"), "url": a.get("drive_web_link") or a.get("url")}
                        for a in (s.get("artifacts") or [])
                    ],
                }
                for s in members
            ],
        })
    return ladder


# --------------------------------------------------------------------------- #
# acts
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# products — what the run built, and the beat each one appears at
# --------------------------------------------------------------------------- #
def build_products(snapshot: dict, events: list[dict]) -> list[dict]:
    """The run's products catalogue, each stamped with ``reveal_seq``.

    ``reveal_seq`` is the beat that made the product: its producer's
    ``step_end``, or — when the plugin attributes the key to no skill — the
    last ``step_end`` of its phase. The honesty rule applies: the replay may
    not show a product before the beat that brought it into being. ``None``
    means no beat in this run places it (its phase recorded no steps, as a
    fork's carried phases can); the player shows those at the final beat.
    """
    catalogue = (snapshot.get("current_run") or {}).get("products") or []
    by_skill: dict[str, int] = {}
    by_phase: dict[str, int] = {}
    for e in events:
        if e.get("kind") != "step_end":
            continue
        if e.get("skill"):
            by_skill[e["skill"]] = e["seq"]
        by_phase[e.get("phase") or ""] = e["seq"]

    out = []
    for item in catalogue:
        if not isinstance(item, dict):
            continue
        producer = item.get("producer")
        seq = by_skill.get(producer) if producer else None
        if seq is None:
            seq = by_phase.get(item.get("phase") or "")
        out.append({**item, "reveal_seq": seq})
    return out


# --------------------------------------------------------------------------- #
# flow — what each skill took in and handed on
# --------------------------------------------------------------------------- #
#: Agents whose reads are bookkeeping rather than hand-offs: the orchestrator
#: reads nearly everything to decide what runs next, and listing it as a
#: consumer of every file buries the real downstream skills.
_BOOKKEEPING_CONSUMERS = frozenset({"ace-orchestrator"})


def _first_sentence(text: str, limit: int = 180) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    cut = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    if len(cut) > limit:
        cut = cut[: limit - 1].rstrip() + "…"
    return cut


def _manifest_artifacts() -> list[dict]:
    """The plugin's artifact manifest, as ``apps.system.reader`` parses it."""
    from django.conf import settings

    from apps.system.reader import load_system_overview

    try:
        overview = load_system_overview(getattr(settings, "ACE_PLUGIN_PATH", "") or "")
    except Exception:  # noqa: BLE001 — the flow panel is optional
        log.warning("replay: artifact manifest unavailable", exc_info=True)
        return []
    arts = overview.get("artifacts") or []
    return [a for a in arts if isinstance(a, dict)]


def build_flow(ladder: list[dict], manifest: list[dict] | None = None) -> dict[str, dict]:
    """``{skill: {inputs, outputs}}`` for every skill in the run's plan.

    Read from the plugin's artifact manifest (``lib/artifact-manifest.ts``):
    each entry declares the skill that produces it (``producedBy``) and the
    skills that read it (``consumedBy``). That is the DECLARED flow — what the
    plugin says each skill hands on — not a trace of this run's reads, and the
    panel labels it that way.

    * ``inputs``  — entries this skill consumes that something else produced.
    * ``outputs`` — entries this skill produces, with who reads them.

    Producer and consumer phases come from the run's own ladder where the
    skill is in it, so they number the way the rest of the screen does.
    """
    manifest = _manifest_artifacts() if manifest is None else manifest
    phase_of: dict[str, str] = {}
    for phase in ladder:
        for step in phase.get("steps") or []:
            if step.get("skill"):
                phase_of[step["skill"]] = phase.get("phase") or ""

    flow: dict[str, dict] = {skill: {"inputs": [], "outputs": []} for skill in phase_of}
    for entry in manifest:
        path = str(entry.get("path") or "")
        if not path:
            continue
        producer = str(entry.get("produced_by") or "")
        consumers = [
            str(c) for c in (entry.get("consumed_by") or [])
            if isinstance(c, str) and c
        ]
        description = _first_sentence(entry.get("description") or "")
        for consumer in consumers:
            if consumer not in flow or consumer == producer:
                continue
            flow[consumer]["inputs"].append({
                "path": path,
                "description": description,
                "producer": producer or None,
                "producer_phase": phase_of.get(producer) or entry.get("phase") or None,
            })
        if producer in flow:
            downstream = [
                c for c in consumers if c != producer and c not in _BOOKKEEPING_CONSUMERS
            ]
            flow[producer]["outputs"].append({
                "path": path,
                "description": description,
                "consumers": [
                    {"skill": c, "phase": phase_of.get(c)} for c in dict.fromkeys(downstream)
                ],
            })
    return flow


def build_acts(snapshot: dict) -> tuple[list[dict], dict]:
    """The act list and capability map for one run.

    One act today — the step-through timeline the Phases screen replays. The
    list shape is kept (rather than returning the timeline bare) so the payload
    stays stable for the one consumer; the standalone player's other acts
    (time ledger, gates, decisions) were removed with that player.
    """
    timeline = build_timeline(snapshot)
    has_events = bool(timeline["events"])
    ladder = build_ladder(snapshot)
    acts = [
        {
            "id": "timeline",
            "title": "The run",
            "available": has_events,
            "unavailable_reason": None if has_events else "This run has no completed steps yet.",
            "data": {
                **timeline,
                "ladder": ladder,
                "products": build_products(snapshot, timeline["events"]),
                "flow": build_flow(ladder),
            },
        },
    ]
    return acts, {a["id"]: a["available"] for a in acts}


def build_replay_payload(snapshot: dict, *, run_id: str | None = None) -> dict:
    """Assemble the full replay payload from a rich snapshot dict."""
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
