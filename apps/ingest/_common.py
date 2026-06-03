"""Pure helpers shared by cost_aggregator and structure_aggregator.

No Django imports at module load time — `skill_phase_index` does a lazy
import so tests can monkeypatch and pure unit tests don't drag the ORM.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def empty_tokens() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
    }


def add_usage(target: dict[str, int], usage: dict[str, Any] | None) -> None:
    if not usage:
        return
    target["input_tokens"] += usage.get("input_tokens", 0) or 0
    target["output_tokens"] += usage.get("output_tokens", 0) or 0
    target["cache_creation_tokens"] += usage.get("cache_creation_input_tokens", 0) or 0
    target["cache_read_tokens"] += usage.get("cache_read_input_tokens", 0) or 0


def wall_time_seconds(start: datetime | None, end: datetime | None) -> int:
    if start is None or end is None:
        return 0
    delta = (end - start).total_seconds()
    return max(0, int(round(delta)))


def union_seconds(intervals: list[tuple[datetime | None, datetime | None]]) -> int:
    """Wall-clock seconds covered by the UNION of [start, end] intervals.

    Overlapping intervals are merged so wall-clock time shared by two segments
    is counted once. This is the correct way to roll up per-phase / per-skill
    wall time: summing raw segment spans double-counts any window covered by
    both a skill segment and the orchestration span that brackets it.

    Intervals with a missing endpoint, or where end precedes start, are dropped.
    """
    clean = [
        (s, e) for (s, e) in intervals
        if s is not None and e is not None and e >= s
    ]
    if not clean:
        return 0
    clean.sort(key=lambda iv: iv[0])
    total = 0.0
    cur_start, cur_end = clean[0]
    for s, e in clean[1:]:
        if s > cur_end:
            total += (cur_end - cur_start).total_seconds()
            cur_start, cur_end = s, e
        elif e > cur_end:
            cur_end = e
    total += (cur_end - cur_start).total_seconds()
    return max(0, int(round(total)))


def registry_lookup(phase_index: dict[str, dict], name: str) -> dict | None:
    """Look up a skill or agent in the phase index, with namespace fallback.

    JSONL transcripts identify skills/agents with the plugin namespace prefix
    (e.g. "ace:idea-to-pdd"). The registry indexes by the unprefixed name from
    each agent's frontmatter. Try the literal name first, then strip the
    "<namespace>:" prefix and try again.
    """
    direct = phase_index.get(name)
    if direct is not None:
        return direct
    if ":" in name:
        return phase_index.get(name.split(":", 1)[1])
    return None


def skill_phase_index() -> dict[str, dict]:
    """Return {skill_name: {phase, phase_display, phase_ordinal}} from the ACE plugin registry.

    Lazy import + exception guard keeps this module pure (no hard Django dep
    at module load) and lets tests monkeypatch `skill_phase_index` in isolation.
    """
    try:
        from apps.system.reader import get_skill_phase_index  # noqa: PLC0415

        return get_skill_phase_index()
    except Exception:
        return {}
