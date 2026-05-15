"""`/ace status` and `/ace list` read-only queries."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.conf import settings

from apps.opps.api import list_opp_cards

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
    """`/ace list opps` (workspace-wide) | `/ace list runs` (your tracked
    Slack runs). Bare `/ace list` falls back to `opps` since that's almost
    always what people mean."""
    sub = (rest or "").strip().lower() or "opps"
    if sub.startswith("opp"):
        return _list_opps(installation=installation)
    if sub.startswith("run"):
        return _list_runs(installation=installation, user_link=user_link)
    return {
        "response_type": "ephemeral",
        "text": "Usage: `/ace list opps` or `/ace list runs`.",
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
        phase = c.get("current_phase") or "—"
        skill = c.get("current_skill") or c.get("current_step")
        run_count = c.get("run_count") or 0
        skill_bit = f" · `{skill}`" if skill else ""
        permalink = (f"{settings.ACE_PUBLIC_BASE_URL}/w/"
                     f"{workspace.slug}/opps/{slug}")
        lines.append(
            f"• <{permalink}|*{title}*> · `{slug}` · {run_count} run"
            f"{'s' if run_count != 1 else ''} · phase: {phase}{skill_bit}"
        )
    return {"response_type": "ephemeral",
            "text": f"Opps in `{workspace.slug}` (top {len(cards)}):\n" + "\n".join(lines)}


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
