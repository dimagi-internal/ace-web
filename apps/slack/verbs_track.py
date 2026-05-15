"""`/ace track <slug>[/<run_id>]` and `/ace untrack <slug>` subcommands.

Used to mirror a run that wasn't triggered through Slack — typically one a
human is driving from `claude -p /ace:run` on their laptop. The handler
creates a `SlackRunThread` row pointing at (slug, run_id) and posts the
initial parent card. The dispatcher's periodic sweep takes it from there;
no `opp.updated` push arrives for laptop runs, but `dispatch_tick`
re-loads the snapshot which goes through the Drive Changes API and picks
up any new Drive writes.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.conf import settings

from .blocks import render_parent_card
from .models import SlackRunThread
from .slack_client import SlackClient, client_for

logger = logging.getLogger(__name__)


def _get_client(installation) -> SlackClient:
    """Indirection so tests can patch."""
    return client_for(installation)


def _load_snapshot(slug: str, workspace, run_id: str | None = None) -> dict | None:
    """Indirection so tests can patch."""
    from apps.opps.api import load_opp_snapshot
    return load_opp_snapshot(workspace, slug, run_id=run_id)


def _parse_track_arg(rest: str) -> tuple[str, str | None]:
    """Parse `<slug>` or `<slug>/<run_id>`.

    Returns (slug, run_id_or_None). Empty input raises ValueError.
    """
    rest = rest.strip()
    if not rest:
        raise ValueError("missing slug")
    if "/" in rest:
        slug, run_id = rest.split("/", 1)
        return slug.strip(), run_id.strip() or None
    return rest, None


def handle_track(*, installation, user_link, rest: str, channel_id: str) -> dict:
    try:
        slug, requested_run_id = _parse_track_arg(rest)
    except ValueError:
        return {
            "response_type": "ephemeral",
            "text": (
                "Usage: `/ace track <opp-slug>[/<run_id>]`. "
                "Example: `/ace track rural-tb` or `/ace track rural-tb/20260515-1015`."
            ),
        }

    workspace = installation.ace_workspace

    # Load the snapshot to figure out which run to track (and to render the
    # initial parent card). load_opp_snapshot returns None if the opp doesn't
    # exist in this workspace.
    snapshot = _load_snapshot(slug, workspace, run_id=requested_run_id)
    if snapshot is None:
        return {
            "response_type": "ephemeral",
            "text": f":x: No opp `{slug}` in workspace `{workspace.slug}`.",
        }

    run_id = requested_run_id or snapshot.get("current_run", {}).get("run_id") or ""
    if not run_id:
        return {
            "response_type": "ephemeral",
            "text": f":x: Opp `{slug}` has no runs yet — nothing to track.",
        }

    # Refuse to create a second active thread for the same (slug, run_id).
    existing = SlackRunThread.objects.filter(
        opp_slug=slug, run_id=run_id,
        broken_at__isnull=True, stopped_at__isnull=True,
    ).first()
    if existing is not None:
        permalink = (
            f"{settings.ACE_PUBLIC_BASE_URL}/w/{workspace.slug}/opps/{slug}"
        )
        return {
            "response_type": "ephemeral",
            "text": (
                f"`{slug}/{run_id}` is already being tracked in "
                f"<#{existing.channel_id}>. Run is at {permalink}."
            ),
        }

    user = user_link.ace_user
    client = _get_client(installation)
    blocks = render_parent_card(
        snapshot,
        opp_slug=slug,
        workspace_slug=workspace.slug,
        triggerer_display=f"<@{user_link.slack_user_id}>",
        elapsed_seconds=0,
    )
    ts = client.post_message(
        channel=channel_id,
        blocks=blocks,
        text=f"ACE run · tracking {slug}/{run_id}",
    )
    SlackRunThread.objects.create(
        installation=installation,
        channel_id=channel_id,
        parent_ts=ts,
        opp_slug=slug,
        run_id=run_id,
        ace_user=user,
        source="track",
    )
    return {
        "response_type": "ephemeral",
        "text": (
            f":eyes: Now mirroring `{slug}/{run_id}` in this channel. "
            f"Click *Stop watching* on the parent card to stop."
        ),
    }


def handle_untrack(*, installation, user_link, rest: str) -> dict:
    """Stop mirroring. Matches by slug (most recent active thread)."""
    slug = rest.strip()
    if not slug:
        return {
            "response_type": "ephemeral",
            "text": "Usage: `/ace untrack <slug>`.",
        }
    thread = (
        SlackRunThread.objects
        .filter(
            installation=installation, opp_slug=slug,
            broken_at__isnull=True, stopped_at__isnull=True,
        )
        .order_by("-triggered_at")
        .first()
    )
    if thread is None:
        return {
            "response_type": "ephemeral",
            "text": f":x: No active Slack mirror for `{slug}`.",
        }
    _stop_thread(thread, stopper=user_link.ace_user, installation=installation)
    return {
        "response_type": "ephemeral",
        "text": (
            f":octagonal_sign: Stopped mirroring `{thread.opp_slug}/{thread.run_id}`."
        ),
    }


def _stop_thread(thread: SlackRunThread, *, stopper, installation) -> None:
    """Mark a thread stopped and update the parent card one last time so
    the channel reflects the stop. Shared between `/ace untrack` and the
    inline *Stop watching* block-action handler."""
    thread.stopped_at = datetime.now(UTC)
    thread.stopped_by = stopper
    thread.save(update_fields=["stopped_at", "stopped_by"])
    # Best-effort final parent card refresh. If Slack can't update (channel
    # gone etc.), swallow — the row is stopped regardless.
    workspace = installation.ace_workspace
    snapshot = _load_snapshot(thread.opp_slug, workspace, run_id=thread.run_id or None)
    if snapshot is None:
        return
    # Django's DateTimeField descriptor type confuses basedpyright when
    # `thread` is a typed parameter (vs. inferred via .get()/.first()).
    # The attribute value at runtime is always a datetime.
    triggered_at: datetime = thread.triggered_at
    elapsed = int((datetime.now(UTC) - triggered_at).total_seconds())
    triggerer_display = (
        f"{thread.ace_user.display_name or thread.ace_user.email}"
        if thread.ace_user_id else "ACE"
    )
    stopped_by_display = f"<@{stopper.email}>" if stopper else None
    blocks = render_parent_card(
        snapshot,
        opp_slug=thread.opp_slug,
        workspace_slug=workspace.slug,
        triggerer_display=triggerer_display,
        elapsed_seconds=elapsed,
        stopped_by_display=stopped_by_display,
    )
    try:
        _get_client(installation).update_message(
            channel=thread.channel_id, ts=thread.parent_ts,
            blocks=blocks, text=f"ACE run · {thread.opp_slug} (stopped)",
        )
    except Exception:
        logger.exception("final parent-card update on stop failed for thread %s",
                         thread.pk)
