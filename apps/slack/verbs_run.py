"""`/ace run <slug-or-link>` subcommand."""
from __future__ import annotations

import logging

from .blocks import render_parent_card
from .models import SlackRunThread
from .run_starter import RunStartError, start_run_from_slack
from .slack_client import SlackClient, client_for

logger = logging.getLogger(__name__)


def _get_client(installation) -> SlackClient:
    """Indirection so tests can patch."""
    return client_for(installation)


def _lookup_active_run(*, workspace, slug: str) -> tuple[str, str] | None:
    """Return (slug, run_id) of an active Slack-tracked run for this
    opp, or None. v1 implementation — checks SlackRunThread directly."""
    existing = (SlackRunThread.objects
                .filter(opp_slug=slug, broken_at__isnull=True)
                .order_by("-triggered_at").first())
    return (existing.opp_slug, existing.run_id) if existing else None


def handle_run(*, installation, user_link, rest: str, channel_id: str,
               trigger_id: str) -> dict:
    rest = rest.strip()
    if not rest:
        return {
            "response_type": "ephemeral",
            "text": (
                "Usage: `/ace run <opp-slug-or-pdd-link>`. "
                "Example: `/ace run rural-health-tb-screening`."
            ),
        }

    workspace = installation.ace_workspace
    user = user_link.ace_user

    # Duplicate-run short circuit (only for slug args; PDD-link / idea
    # triggers always create a new opp, so no dedup needed).
    if not rest.startswith("https://") and not rest.startswith("idea:"):
        existing = _lookup_active_run(workspace=workspace, slug=rest)
        if existing is not None:
            slug, run_id = existing
            thread = SlackRunThread.objects.filter(
                opp_slug=slug, run_id=run_id,
            ).first()
            permalink = (
                f"https://labs.connect.dimagi.com/ace/w/"
                f"{workspace.slug}/opps/{slug}"
            )
            return {
                "response_type": "ephemeral",
                "text": (
                    f"`{slug}` is already running ({run_id}). "
                    f"See: {permalink}"
                    + (f" · thread: <#{thread.channel_id}>" if thread else "")
                ),
            }

    try:
        slug, run_id = start_run_from_slack(
            slug_or_link=rest, user=user, workspace=workspace,
        )
    except RunStartError as e:
        return {"response_type": "ephemeral", "text": f":x: {e}"}
    except Exception:
        logger.exception("start_run_from_slack failed")
        return {
            "response_type": "ephemeral",
            "text": ":x: Internal error starting run. Check ace-web logs.",
        }

    # Post the initial parent card. Snapshot may not be available yet
    # (run just started), so render a placeholder.
    placeholder_snapshot = {
        "display_name": slug,
        "current_run": {"run_id": run_id, "steps": [], "decisions": []},
        "phases": [],
    }
    client = _get_client(installation)
    blocks = render_parent_card(
        placeholder_snapshot,
        opp_slug=slug,
        workspace_slug=workspace.slug,
        triggerer_display=f"<@{user_link.slack_user_id}>",
        elapsed_seconds=0,
    )
    ts = client.post_message(
        channel=channel_id, blocks=blocks, text=f"ACE run started — {slug}"
    )
    SlackRunThread.objects.create(
        installation=installation,
        channel_id=channel_id,
        parent_ts=ts,
        opp_slug=slug,
        run_id=run_id,
        ace_user=user,
    )
    # Group-add to the consumer is wired in Task 13; for now the row
    # exists and the 60s sweep (Task 15) will catch it up once the
    # consumer is running.

    return {
        "response_type": "ephemeral",
        "text": (
            f":rocket: Kicking off `{slug}` ({run_id}). "
            "Watch the thread for progress."
        ),
    }
