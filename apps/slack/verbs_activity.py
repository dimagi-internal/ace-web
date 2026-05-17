"""`/ace activity` — workspace 'what's running' view, full Block Kit treatment.

Same data primitive (apps.activity.api.get_workspace_activity) that the
ace-web Activity page consumes; this surface renders it as a thread of
section blocks + per-row action accessories.

Per the design doc: observable facts only. Timestamps and source labels
('ace-web' / 'Drive only') describe what we observed — never claim a
plugin is alive.
"""
from __future__ import annotations

import datetime as dt
import logging

from django.conf import settings

from apps.activity.api import get_workspace_activity

from .async_response import run_async

logger = logging.getLogger(__name__)

# Slack caps tighter than the API default — keep the thread skim-able.
_SLACK_ROW_LIMIT = 10


def handle_activity(
    *, installation, user_link, rest: str, channel_id: str,
    response_url: str = "",
) -> dict:
    """`/ace activity` (default) | `/ace activity --all` (include recent
    completed).

    The data fetch hits Drive (1-2s warm, 5-15s cold), so we always go
    through response_url when one is provided."""
    args = (rest or "").strip().lower()
    include_completed = "--all" in args or "all" in args.split()

    if response_url:
        run_async(
            response_url, _build_activity_response,
            installation=installation, include_completed=include_completed,
        )
        return {
            "response_type": "ephemeral",
            "text": ":hourglass_flowing_sand: Loading workspace activity…",
        }
    return _build_activity_response(
        installation=installation, include_completed=include_completed,
    )


def _build_activity_response(*, installation, include_completed: bool) -> dict:
    workspace = installation.ace_workspace
    try:
        result = get_workspace_activity(
            workspace, include_completed=include_completed,
            limit=_SLACK_ROW_LIMIT,
        )
    except Exception:
        logger.exception("get_workspace_activity failed for %s", workspace.slug)
        return {
            "response_type": "ephemeral",
            "text": ":x: Couldn't load workspace activity — check ace-web logs.",
        }
    rows = result.get("rows", [])
    server_now = result.get("server_now")
    if not rows:
        msg = (
            "No active runs in this workspace right now."
            if not include_completed
            else "No activity in this workspace in the last 24h. "
                 "Try `/ace run <slug>` or `/ace new` to start one."
        )
        return {"response_type": "ephemeral", "text": msg}

    blocks = _render_activity_blocks(
        rows=rows, workspace_slug=workspace.slug,
        server_now=server_now, include_completed=include_completed,
    )
    return {
        "response_type": "ephemeral",
        "text": f"Workspace activity · {workspace.slug}",
        "blocks": blocks,
    }


def _render_activity_blocks(
    *, rows: list[dict], workspace_slug: str,
    server_now: str | None, include_completed: bool,
) -> list[dict]:
    """Build a single section block holding the whole table as mrkdwn
    bullets. One line per row, opp name is a hyperlink (no Open button
    needed). Drastically more compact than per-row section blocks.

    Layout:
      [Context header]
      [Section: bulleted list, one line per row]
      [Context footer]
    """
    base_url = getattr(
        settings, "ACE_PUBLIC_BASE_URL",
        "https://labs.connect.dimagi.com/ace",
    )
    active_count = sum(1 for r in rows if r.get("lifecycle_status") != "complete")
    header_text = (
        f":satellite_antenna: *Workspace activity · `{workspace_slug}`* — "
        f"{active_count} active"
        + (f" / {len(rows)} total" if include_completed and active_count != len(rows) else "")
    )
    now_dt = _parse_iso(server_now) if server_now else dt.datetime.now(dt.UTC)
    lines = [_render_row_line(r, now=now_dt, base_url=base_url) for r in rows]
    body = "\n".join(lines)

    footer = (
        f"_Sorted by recency · `/ace activity{' --all' if not include_completed else ''}` "
        f"to {'include' if not include_completed else 'see only active'} "
        f"{'recent completed' if not include_completed else 'runs'} · "
        f"`/ace track <slug>` to mirror a run in this channel_"
    )
    return [
        {"type": "context",
         "elements": [{"type": "mrkdwn", "text": header_text}]},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": body}},
        {"type": "context",
         "elements": [{"type": "mrkdwn", "text": footer}]},
    ]


def _render_row_line(row: dict, *, now: dt.datetime, base_url: str) -> str:
    """One markdown line per row. No per-row Block Kit — pure mrkdwn.

    Format:
      • *<title link>* · `run-id` · <state> · <source · Nm ago>

    The opp name itself is the hyperlink, so no Open button needed.
    """
    opp_slug = row.get("opp_slug") or "?"
    display_name = row.get("opp_display_name") or opp_slug
    run_id = row.get("run_id") or ""
    last_activity_at = row.get("last_activity_at")
    last_activity_dt = _parse_iso(last_activity_at) if last_activity_at else None
    delta = _human_delta(now - last_activity_dt) if last_activity_dt else None

    phase = row.get("current_phase_display") or row.get("current_phase_name")
    source_hint = row.get("source_hint") or "drive-only"
    source_actor = row.get("source_actor_email")
    phase_url = row.get("phase_url") or f"{base_url}/w/?/opps/{opp_slug}"

    # Observable-facts-only state token. We show a phase ONLY when one is
    # actually in progress. When current_phase is None we honestly don't
    # know if the run completed cleanly or crashed — say nothing rather
    # than guess.
    state_bit = f"`{phase}`" if phase else ""

    source_label = (
        f"ace-web · {source_actor}" if source_hint == "ace-web" and source_actor
        else "ace-web" if source_hint == "ace-web"
        else "Drive only"
    )
    recency = f"_{source_label} · {delta}_" if delta else f"_{source_label}_"

    parts = [f"*<{phase_url}|{display_name}>*", f"`{run_id}`"]
    if state_bit:
        parts.append(state_bit)
    parts.append(recency)
    return "• " + " · ".join(parts)


def _parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def _human_delta(delta: dt.timedelta) -> str:
    """Render a timedelta as a compact recency string ('3m ago', '47m ago')."""
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"
