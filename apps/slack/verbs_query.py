"""`/ace status` and `/ace list` read-only queries."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from django.conf import settings

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

    elapsed = int((datetime.now(timezone.utc) - thread.triggered_at).total_seconds())
    blocks = render_parent_card(
        snap, opp_slug=thread.opp_slug, workspace_slug=workspace.slug,
        triggerer_display=f"<@{user_link.slack_user_id}>",
        elapsed_seconds=elapsed,
    )
    return {"response_type": "ephemeral", "blocks": blocks,
            "text": f"Status of {thread.opp_slug}"}


def handle_list(*, installation, user_link, channel_id: str) -> dict:
    threads = (SlackRunThread.objects
               .filter(installation=installation, ace_user=user_link.ace_user,
                       broken_at__isnull=True)
               .order_by("-triggered_at")[:5])
    if not threads:
        return {"response_type": "ephemeral",
                "text": "You have no active runs. Try `/ace run <slug>`."}
    lines = [f"• `{t.opp_slug}` ({t.run_id}) — "
             f"<{settings.ACE_PUBLIC_BASE_URL}/w/"
             f"{installation.ace_workspace.slug}/opps/{t.opp_slug}|open ↗>"
             for t in threads]
    return {"response_type": "ephemeral",
            "text": "Your recent ACE runs:\n" + "\n".join(lines)}
