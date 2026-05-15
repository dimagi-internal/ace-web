"""Pure Block Kit renderers. Snapshot in, list[dict] out.

These mirror the shape of frontend/src/components/views/PhaseView.tsx
PhaseTile + the WorkbenchHeader parent card. State hashes are computed
from the same fields the renderer reads, so any user-visible diff is
caught by the hash check.

Snapshot shape: we treat the snapshot as a dict with keys
{display_name, current_run.{run_id, steps[]}, phases[]}. The real
OppSnapshot is a Pydantic model; the dispatcher serializes it via
.model_dump() before calling these renderers (keeps the renderers
test-friendly without Pydantic imports).
"""
from __future__ import annotations

import hashlib
import json

_BAR_WIDTH = 10
_PROD_BASE_URL = "https://labs.connect.dimagi.com/ace"


def render_progress_bar(complete: int, total: int) -> str:
    pct = 0 if total == 0 else int(round(100 * complete / total))
    filled = 0 if total == 0 else round(_BAR_WIDTH * complete / total)
    return ("▓" * filled) + ("░" * (_BAR_WIDTH - filled)) + f" {pct}%"


def _phase_stats(snapshot: dict, phase_name: str) -> dict:
    steps = [s for s in snapshot["current_run"]["steps"]
             if s["phase"] == phase_name]
    complete = sum(1 for s in steps if s["status"] == "complete")
    qa_failed = sum(1 for s in steps if s["status"] == "qa-failed")
    open_decisions = 0  # Decisions live on current_run; populated below.
    decisions = snapshot.get("current_run", {}).get("decisions") or []
    open_decisions = sum(1 for d in decisions
                         if d.get("phase") == phase_name and d.get("status") == "open")
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
        "open_decisions": open_decisions,
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


def render_phase_tile(snapshot: dict, *, phase_name: str,
                      opp_slug: str, workspace_slug: str) -> list[dict]:
    phase = _phase_info(snapshot, phase_name)
    stats = _phase_stats(snapshot, phase_name)
    bar = render_progress_bar(stats["complete"], stats["total"])

    eyebrow = f"Phase {phase['ordinal']} · {phase['agent']}"
    title = f"*{phase['display_name']}*"

    context_bits = [f"{stats['complete']}/{stats['total']} done"]
    if stats["mean_score"] is not None:
        context_bits.append(f"mean {stats['mean_score']}/100")
    if stats["qa_failed"] > 0:
        context_bits.append(f":x: {stats['qa_failed']} qa-failed")
    if stats["open_decisions"] > 0:
        context_bits.append(f":grey_question: {stats['open_decisions']} open")

    blocks: list[dict] = [
        {"type": "context",
         "elements": [{"type": "mrkdwn", "text": eyebrow}]},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": title}},
        {"type": "context",
         "elements": [{"type": "mrkdwn", "text": " · ".join(context_bits)}]},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": f"`{bar}`"}},
    ]
    if stats["current_skill"]:
        blocks.append({"type": "context",
                       "elements": [{"type": "mrkdwn",
                                     "text": f"Currently: {stats['current_skill']}"}]})

    action_elements = [{
        "type": "button",
        "text": {"type": "plain_text", "text": "View phase ↗"},
        "url": f"{_PROD_BASE_URL}/w/{workspace_slug}/opps/{opp_slug}",
        "action_id": f"view_phase:{opp_slug}:{phase_name}",
    }]
    if stats["has_any_complete"]:
        action_elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "🍴 Fork from here…"},
            "action_id": "fork_from_phase",
            "value": f"{opp_slug}:{phase_name}",
        })
    blocks.append({"type": "actions", "elements": action_elements})
    return blocks


def _active_phase(snapshot: dict) -> dict | None:
    for p in sorted(snapshot["phases"], key=lambda x: x["ordinal"]):
        stats = _phase_stats(snapshot, p["name"])
        if stats["total"] == 0:
            continue
        if not stats["terminal"]:
            return p
    return None


def render_parent_card(snapshot: dict, *, opp_slug: str, workspace_slug: str,
                       triggerer_display: str, elapsed_seconds: int) -> list[dict]:
    active = _active_phase(snapshot)
    elapsed_min = elapsed_seconds // 60
    run_id = snapshot["current_run"]["run_id"]
    if active:
        active_stats = _phase_stats(snapshot, active["name"])
        active_line = (f"Phase {active['ordinal']} · *{active['display_name']}*"
                       + (f" · running `{active_stats['current_skill']}`"
                          if active_stats["current_skill"] else ""))
    else:
        active_line = "All phases complete · awaiting cleanup"

    text = (f"*{snapshot['display_name']}* — `{run_id}`\n"
            f"Triggered by {triggerer_display} · {elapsed_min}m elapsed\n"
            f"{active_line}")

    return [
        {"type": "section",
         "text": {"type": "mrkdwn", "text": text}},
        {"type": "actions", "elements": [
            {"type": "button",
             "text": {"type": "plain_text", "text": "Open in ace-web ↗"},
             "url": f"{_PROD_BASE_URL}/w/{workspace_slug}/opps/{opp_slug}"},
        ]},
    ]


def phase_state_hash(snapshot: dict, phase_name: str) -> str:
    stats = _phase_stats(snapshot, phase_name)
    payload = {
        "complete": stats["complete"],
        "total": stats["total"],
        "qa_failed": stats["qa_failed"],
        "open_decisions": stats["open_decisions"],
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
