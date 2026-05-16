"""`/ace status` and `/ace list` read-only queries."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.conf import settings

from apps.opps.api import list_opp_cards, list_opp_runs_for_workspace

from .blocks import render_parent_card
from .models import SlackRunThread

logger = logging.getLogger(__name__)


def _load_snapshot(slug: str, workspace, run_id: str | None = None) -> dict | None:
    """Indirection so tests can patch."""
    from apps.opps.api import load_opp_snapshot
    return load_opp_snapshot(workspace, slug, run_id=run_id)


def handle_status(*, installation, user_link, rest: str, channel_id: str) -> dict:
    workspace = installation.ace_workspace
    rest = rest.strip()
    if rest:
        thread = SlackRunThread.objects.filter(
            installation=installation, opp_slug=rest, broken_at__isnull=True,
        ).order_by("-triggered_at").first()
    else:
        thread = SlackRunThread.objects.filter(
            installation=installation, ace_user=user_link.ace_user,
            broken_at__isnull=True,
        ).order_by("-triggered_at").first()

    if thread is None:
        return {"response_type": "ephemeral",
                "text": "You have no active runs. Try `/ace run <slug>`."}

    snap = _load_snapshot(thread.opp_slug, workspace, run_id=thread.run_id or None)
    if snap is None:
        return {"response_type": "ephemeral",
                "text": f"Could not load snapshot for `{thread.opp_slug}`."}

    elapsed = int((datetime.now(UTC) - thread.triggered_at).total_seconds())
    blocks = render_parent_card(
        snap, opp_slug=thread.opp_slug, workspace_slug=workspace.slug,
        triggerer_display=f"<@{user_link.slack_user_id}>",
        elapsed_seconds=elapsed,
    )
    return {"response_type": "ephemeral", "blocks": blocks,
            "text": f"Status of {thread.opp_slug}"}


def handle_list(*, installation, user_link, rest: str, channel_id: str) -> dict:
    """`/ace list opps`                — workspace-wide opp list
    `/ace list runs`                — your active Slack-tracked runs
    `/ace list runs <slug>`         — every run for an opp (from Drive,
                                      not limited to ones you tracked)
    Bare `/ace list` falls back to `opps`."""
    parts = (rest or "").strip().split(maxsplit=1)
    sub = parts[0].lower() if parts else "opps"
    sub_arg = parts[1].strip() if len(parts) > 1 else ""
    if sub == "" or sub.startswith("opp"):
        return _list_opps(installation=installation)
    if sub.startswith("run"):
        if sub_arg:
            return _list_runs_for_opp(installation=installation, slug=sub_arg)
        return _list_runs(installation=installation, user_link=user_link)
    return {
        "response_type": "ephemeral",
        "text": ("Usage: `/ace list opps` · `/ace list runs` · "
                 "`/ace list runs <slug>`."),
    }


def _list_opps(*, installation) -> dict:
    """List the workspace's opps (top 10, most-recently-active first)."""
    workspace = installation.ace_workspace
    try:
        cards = list_opp_cards(workspace)
    except Exception:
        logger.exception("list_opp_cards failed for %s", workspace.slug)
        return {"response_type": "ephemeral",
                "text": ":x: Couldn't load opp list — check ace-web logs."}
    if not cards:
        return {"response_type": "ephemeral",
                "text": (f"No opps in workspace `{workspace.slug}` yet. "
                         f"Try `/ace new` to create one.")}
    # Sort by updated_at desc; the API may already do this but don't rely on it.
    cards = sorted(cards, key=lambda c: c.get("updated_at") or "", reverse=True)[:10]
    lines = []
    for c in cards:
        slug = c.get("slug") or c.get("opp_slug") or "?"
        title = c.get("title") or c.get("display_name") or slug
        # Phase fallback chain: in-progress current_phase → "status" (e.g.
        # "complete", "qa-failed") → "—". Without the fallback every
        # finished run renders as `phase: —` which looks broken.
        phase = c.get("current_phase") or ""
        status = c.get("status") or ""
        state = phase if phase else status if status and status != "unknown" else "—"
        skill = c.get("current_skill") or c.get("current_step")
        run_count = c.get("run_count") or 0
        skill_bit = f" · `{skill}`" if skill and phase else ""
        permalink = (f"{settings.ACE_PUBLIC_BASE_URL}/w/"
                     f"{workspace.slug}/opps/{slug}")
        lines.append(
            f"• <{permalink}|*{title}*> · `{slug}` · {run_count} run"
            f"{'s' if run_count != 1 else ''} · {state}{skill_bit}"
        )
    return {"response_type": "ephemeral",
            "text": f"Opps in `{workspace.slug}` (top {len(cards)}):\n" + "\n".join(lines)}


def _list_runs_for_opp(*, installation, slug: str) -> dict:
    """List every run for a specific opp, sourced from Drive (not limited
    to Slack-triggered/tracked runs). Used for `/ace list runs <slug>`."""
    workspace = installation.ace_workspace
    try:
        runs = list_opp_runs_for_workspace(workspace, slug)
    except Exception:
        logger.exception("list_opp_runs_for_workspace failed for %s/%s",
                         workspace.slug, slug)
        return {"response_type": "ephemeral",
                "text": f":x: Couldn't load runs for `{slug}` — check ace-web logs."}
    if not runs:
        return {"response_type": "ephemeral",
                "text": (f"No runs for `{slug}` in workspace `{workspace.slug}`. "
                         f"(Or the opp doesn't exist.)")}
    # Sort by last activity desc.
    runs = sorted(runs, key=lambda r: r.get("started_at") or "", reverse=True)[:10]
    base = f"{settings.ACE_PUBLIC_BASE_URL}/w/{workspace.slug}/opps/{slug}"
    lines = []
    for r in runs:
        run_id = r.get("run_id") or "?"
        lifecycle = r.get("lifecycle_status") or "—"
        cur_phase = r.get("current_phase_display") or r.get("current_phase") or ""
        done = r.get("latest_phase_done_display") or r.get("latest_phase_done") or ""
        state_bit = cur_phase or done or lifecycle
        is_active = r.get("is_active")
        marker = "🟡" if is_active else "✅" if lifecycle == "complete" else "⚪"
        lines.append(
            f"{marker} <{base}?run_id={run_id}|`{run_id}`> · {state_bit}"
        )
    return {"response_type": "ephemeral",
            "text": (f"Runs for `{slug}` ({len(runs)} of "
                     f"{len(runs)} shown):\n" + "\n".join(lines))}


def _list_runs(*, installation, user_link) -> dict:
    """List the user's Slack-tracked runs."""
    threads = (SlackRunThread.objects
               .filter(installation=installation, ace_user=user_link.ace_user,
                       broken_at__isnull=True, stopped_at__isnull=True)
               .order_by("-triggered_at")[:5])
    if not threads:
        return {"response_type": "ephemeral",
                "text": ("You have no active Slack-tracked runs. "
                         "Try `/ace run <slug>` or `/ace track <slug>`.")}
    lines = [f"• `{t.opp_slug}` ({t.run_id}) — "
             f"<{settings.ACE_PUBLIC_BASE_URL}/w/"
             f"{installation.ace_workspace.slug}/opps/{t.opp_slug}|open ↗>"
             for t in threads]
    return {"response_type": "ephemeral",
            "text": "Your recent Slack-tracked runs:\n" + "\n".join(lines)}
