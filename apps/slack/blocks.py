"""Pure Block Kit renderers. Snapshot in, list[dict] out.

Snapshot shape: dict with keys {display_name, current_run.{run_id,
steps[], decisions[]}, phases[]}. The real OppSnapshot is a Pydantic
model; the dispatcher serializes via .model_dump() before calling
these renderers.
"""
from __future__ import annotations

import hashlib
import json

from django.conf import settings


def _phase_stats(snapshot: dict, phase_name: str) -> dict:
    steps = [s for s in snapshot["current_run"]["steps"]
             if s["phase"] == phase_name]
    complete = sum(1 for s in steps if s["status"] == "complete")
    qa_failed = sum(1 for s in steps if s["status"] == "qa-failed")
    decisions = snapshot.get("current_run", {}).get("decisions") or []
    phase_decisions = [d for d in decisions if d.get("phase") == phase_name]
    overridden = sum(1 for d in phase_decisions
                     if d.get("status") == "overridden")
    judged = [s["judge"]["score_pct"] for s in steps
              if s.get("judge") and s["judge"].get("score_pct") is not None]
    mean_score = round(sum(judged) / len(judged)) if judged else None
    running = next((s for s in steps if s["status"] == "running"), None)
    statuses = {s["status"] for s in steps}
    terminal = bool(steps) and not (statuses & {"running", "pending", "queued"})
    return {
        "total": len(steps),
        "complete": complete,
        "qa_failed": qa_failed,
        "decision_count": len(phase_decisions),
        "overridden_count": overridden,
        "mean_score": mean_score,
        "current_skill": running["skill_name"] if running else None,
        "terminal": terminal,
        "has_any_complete": complete > 0,
    }


def _phase_info(snapshot: dict, phase_name: str) -> dict:
    for p in snapshot["phases"]:
        if p["name"] == phase_name:
            return p
    raise KeyError(f"phase {phase_name!r} not in snapshot")


def _opp_url(workspace_slug: str, opp_slug: str) -> str:
    return f"{settings.ACE_PUBLIC_BASE_URL}/w/{workspace_slug}/opps/{opp_slug}"


def render_phase_tile(snapshot: dict, *, phase_name: str,
                      opp_slug: str, workspace_slug: str) -> list[dict]:
    phase = _phase_info(snapshot, phase_name)
    stats = _phase_stats(snapshot, phase_name)

    # Compact progress: "3/5 done · mean 82/100"
    progress_parts = [f"{stats['complete']}/{stats['total']} done"]
    if stats["mean_score"] is not None:
        progress_parts.append(f"mean {stats['mean_score']}/100")
    if stats["qa_failed"] > 0:
        progress_parts.append(f"{stats['qa_failed']} failed QA")
    progress = " · ".join(progress_parts)

    # Decision line: "3 decisions (1 overridden)"
    decision_line = ""
    if stats["decision_count"] > 0:
        dc = stats["decision_count"]
        decision_line = f"{dc} decision{'s' if dc != 1 else ''}"
        if stats["overridden_count"] > 0:
            decision_line += f" ({stats['overridden_count']} overridden)"

    # Running skill
    running_line = ""
    if stats["current_skill"]:
        running_line = f"Running: {stats['current_skill']}"

    # Build the body as a single section block
    title = f"*Phase {phase['ordinal']} — {phase['display_name']}*"
    body_lines = [title, progress]
    if decision_line:
        body_lines.append(decision_line)
    if running_line:
        body_lines.append(running_line)

    blocks: list[dict] = [
        {"type": "section",
         "text": {"type": "mrkdwn", "text": "\n".join(body_lines)}},
    ]

    # Action buttons
    base_url = _opp_url(workspace_slug, opp_slug)
    action_elements: list[dict] = [{
        "type": "button",
        "text": {"type": "plain_text", "text": "Open phase"},
        "url": f"{base_url}?view=phase&phase={phase_name}",
        "action_id": f"view_phase:{opp_slug}:{phase_name}",
    }]
    if stats["decision_count"] > 0:
        action_elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Review decisions"},
            "url": f"{base_url}?view=phase&phase={phase_name}",
            "action_id": f"review_decisions:{opp_slug}:{phase_name}",
            "style": "primary",
        })
    blocks.append({"type": "actions", "elements": action_elements})
    return blocks


def _active_phase(snapshot: dict) -> dict | None:
    for p in sorted(snapshot.get("phases") or [], key=lambda x: x["ordinal"]):
        stats = _phase_stats(snapshot, p["name"])
        if stats["total"] == 0:
            continue
        if not stats["terminal"]:
            return p
    return None


def render_parent_card(
    snapshot: dict,
    *,
    opp_slug: str,
    workspace_slug: str,
    triggerer_display: str,
    elapsed_seconds: int,
    thread_id: str | None = None,
    stopped_by_display: str | None = None,
) -> list[dict]:
    active = _active_phase(snapshot)
    elapsed_min = elapsed_seconds // 60
    run_id = snapshot["current_run"]["run_id"]

    if active:
        active_stats = _phase_stats(snapshot, active["name"])
        skill = active_stats["current_skill"]
        skill_part = f" — running {skill}" if skill else ""
        active_line = (f"Phase {active['ordinal']}: "
                       f"*{active['display_name']}*{skill_part}")
    else:
        active_line = "All phases complete"

    lines = [f"*{snapshot['display_name']}*  `{run_id}`"]
    if stopped_by_display:
        lines.append(f"Stopped by {stopped_by_display}")
    else:
        lines.append(f"Started by {triggerer_display} · {elapsed_min}m elapsed")
    lines.append(active_line)
    text = "\n".join(lines)

    base_url = _opp_url(workspace_slug, opp_slug)
    action_elements: list[dict] = [{
        "type": "button",
        "text": {"type": "plain_text", "text": "Open in ace-web"},
        "url": base_url,
        "action_id": f"open_opp:{opp_slug}",
    }]
    if thread_id and not stopped_by_display:
        action_elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Stop watching"},
            "action_id": "stop_watching",
            "value": str(thread_id),
            "style": "danger",
            "confirm": {
                "title": {"type": "plain_text", "text": "Stop watching this run?"},
                "text": {"type": "mrkdwn",
                         "text": (f"Stop posting updates for `{opp_slug}` "
                                  f"in this thread. The run keeps going.")},
                "confirm": {"type": "plain_text", "text": "Stop"},
                "deny": {"type": "plain_text", "text": "Cancel"},
            },
        })

    return [
        {"type": "section",
         "text": {"type": "mrkdwn", "text": text}},
        {"type": "actions", "elements": action_elements},
    ]


def phase_state_hash(snapshot: dict, phase_name: str) -> str:
    stats = _phase_stats(snapshot, phase_name)
    payload = {
        "complete": stats["complete"],
        "total": stats["total"],
        "qa_failed": stats["qa_failed"],
        "decision_count": stats["decision_count"],
        "overridden_count": stats["overridden_count"],
        "mean_score": stats["mean_score"],
        "current_skill": stats["current_skill"],
        "terminal": stats["terminal"],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()


def parent_state_hash(snapshot: dict, *, elapsed_seconds: int) -> str:
    active = _active_phase(snapshot)
    stats = _phase_stats(snapshot, active["name"]) if active else None
    payload = {
        "active_phase": active["name"] if active else None,
        "current_skill": stats["current_skill"] if stats else None,
        "elapsed_min_bucket": elapsed_seconds // 60,
        "run_id": snapshot["current_run"]["run_id"],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()
