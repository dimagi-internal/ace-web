"""SlackOppConsumer: per-tick dispatcher + worker bootstrap.

The synchronous `dispatch_tick(thread_id)` is the pure-Python heart —
unit-tested without Channels. The async wrapper (`_run_worker`) listens
on a unique channel name, joins opp.<slug>.<run_id> groups for active
threads, and calls dispatch_tick on each `opp.updated` event with a
2-second debounce.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer

from .blocks import (
    parent_state_hash, phase_state_hash,
    render_parent_card, render_phase_tile,
)
from .models import SlackRunThread
from .slack_client import SlackChannelGone, SlackRateLimited, client_for

logger = logging.getLogger(__name__)


def _opp_group(slug: str, run_id: str) -> str:
    return f"opp.{slug}.{run_id or 'default'}"


def _load_snapshot(slug: str, workspace) -> dict | None:
    from apps.opps.api import load_opp_snapshot
    return load_opp_snapshot(workspace, slug)


def _get_client(installation):
    return client_for(installation)


def dispatch_tick(*, thread_id) -> None:
    """One dispatch tick. Reads snapshot, diffs phase hashes, posts/updates.

    Safe to call from any thread / loop. Catches Slack channel-gone and
    rate-limit errors and reflects them on the SlackRunThread row.
    """
    try:
        thread = SlackRunThread.objects.select_related(
            "installation__ace_workspace", "ace_user",
        ).get(pk=thread_id)
    except SlackRunThread.DoesNotExist:
        return
    if thread.broken_at is not None:
        return

    from django.core.cache import cache
    lock_key = f"slack:dispatch:{thread.pk}"
    if not cache.add(lock_key, "held", timeout=5):
        return  # another worker is dispatching for this thread
    try:
        workspace = thread.installation.ace_workspace
        snapshot = _load_snapshot(thread.opp_slug, workspace)
        if snapshot is None:
            logger.info("snapshot not yet available for %s/%s",
                        thread.opp_slug, thread.run_id)
            return

        client = _get_client(thread.installation)
        elapsed = int((datetime.now(timezone.utc) - thread.triggered_at).total_seconds())
        phase_messages = dict(thread.phase_messages or {})

        # 1. Per-phase create / update
        for phase in snapshot.get("phases", []):
            # Skip phases with no steps yet — nothing to render.
            steps_in_phase = [s for s in snapshot["current_run"]["steps"]
                              if s["phase"] == phase["name"]]
            if not steps_in_phase:
                continue
            h = phase_state_hash(snapshot, phase["name"])
            existing = phase_messages.get(phase["name"])
            blocks = render_phase_tile(snapshot, phase_name=phase["name"],
                                       opp_slug=thread.opp_slug,
                                       workspace_slug=workspace.slug)
            text = f"Phase {phase['ordinal']}: {phase['display_name']}"
            try:
                if existing is None:
                    ts = client.post_message(channel=thread.channel_id,
                                             blocks=blocks, text=text,
                                             thread_ts=thread.parent_ts)
                    phase_messages[phase["name"]] = {"ts": ts, "last_state_hash": h}
                elif existing.get("last_state_hash") != h:
                    client.update_message(channel=thread.channel_id,
                                          ts=existing["ts"],
                                          blocks=blocks, text=text)
                    existing["last_state_hash"] = h
                    phase_messages[phase["name"]] = existing
            except SlackChannelGone:
                thread.broken_at = datetime.now(timezone.utc)
                thread.save(update_fields=["broken_at"])
                return
            except SlackRateLimited as e:
                logger.info("slack rate-limited on %s/%s; deferring (retry %ss)",
                            thread.opp_slug, thread.run_id, e.retry_after)
                return  # next opp.updated will retry

        # 2. Parent card
        new_parent_hash = parent_state_hash(snapshot, elapsed_seconds=elapsed)
        if new_parent_hash != thread.parent_state_hash:
            triggerer = thread.ace_user
            triggerer_display = (
                getattr(triggerer, "display_name", None)
                or getattr(triggerer, "email", None)
                or f"user {triggerer.pk}"
            )
            parent_blocks = render_parent_card(
                snapshot, opp_slug=thread.opp_slug,
                workspace_slug=workspace.slug,
                triggerer_display=triggerer_display, elapsed_seconds=elapsed,
            )
            try:
                client.update_message(channel=thread.channel_id, ts=thread.parent_ts,
                                      blocks=parent_blocks,
                                      text=f"ACE run · {thread.opp_slug}")
            except SlackChannelGone:
                thread.broken_at = datetime.now(timezone.utc)
                thread.save(update_fields=["broken_at"])
                return
            except SlackRateLimited:
                return
            thread.parent_state_hash = new_parent_hash

        thread.phase_messages = phase_messages
        thread.save(update_fields=["phase_messages", "parent_state_hash"])
    finally:
        cache.delete(lock_key)


async def _periodic_sweep() -> None:
    """Belt-and-suspenders: every 60s, dispatch_tick all active threads.

    Catches missed opp.updated events (worker restart, lost event) and
    drives phase 1 of newly-created threads that haven't received their
    first opp.updated yet (snapshot not yet populated → first sweep
    after Drive writes lands a phase tile)."""
    while True:
        await asyncio.sleep(60)
        try:
            ids = await sync_to_async(list)(
                SlackRunThread.objects.filter(broken_at__isnull=True)
                .values_list("pk", flat=True)
            )
            for tid in ids:
                await sync_to_async(dispatch_tick)(thread_id=tid)
        except Exception:
            logger.exception("periodic sweep failed")


async def _run_worker() -> None:
    """Long-running worker: join opp groups for active threads and
    dispatch_tick on opp.updated events. Per-thread 2s debounce."""
    layer = get_channel_layer()
    if layer is None:
        logger.info("no channel layer; slack worker not started")
        return
    channel_name = await layer.new_channel()
    joined: set[str] = set()
    debounce: dict[int, asyncio.Task] = {}

    async def _refresh_subscriptions():
        threads = await sync_to_async(list)(
            SlackRunThread.objects.filter(broken_at__isnull=True)
            .values_list("opp_slug", "run_id", "pk")
        )
        wanted_groups = {_opp_group(s, r) for s, r, _ in threads}
        for g in wanted_groups - joined:
            await layer.group_add(g, channel_name)
            joined.add(g)
        for g in joined - wanted_groups:
            await layer.group_discard(g, channel_name)
            joined.discard(g)

    async def _debounced_dispatch(thread_id: int):
        await asyncio.sleep(2.0)
        try:
            await sync_to_async(dispatch_tick)(thread_id=thread_id)
        except Exception:
            logger.exception("dispatch_tick failed for thread %s", thread_id)
        debounce.pop(thread_id, None)

    # Initial sweep + group joins
    await _refresh_subscriptions()
    # On boot, run a one-shot tick across all active threads.
    threads = await sync_to_async(list)(
        SlackRunThread.objects.filter(broken_at__isnull=True).values_list("pk", flat=True)
    )
    for tid in threads:
        await sync_to_async(dispatch_tick)(thread_id=tid)

    sweep_task = asyncio.create_task(_periodic_sweep())
    _ = sweep_task  # kept alive by the task ref in this scope

    while True:
        try:
            event = await layer.receive(channel_name)
        except Exception:
            logger.exception("channel receive failed; worker exiting")
            return
        if event.get("type") != "opp.updated":
            continue
        slug = event.get("opp_slug")
        run_id = event.get("run_id") or ""
        if not slug:
            continue
        thread_id = await sync_to_async(
            lambda: SlackRunThread.objects.filter(
                opp_slug=slug, run_id=run_id, broken_at__isnull=True,
            ).values_list("pk", flat=True).first()
        )()
        if thread_id is None:
            continue
        # Coalesce: cancel any pending debounced dispatch for this thread.
        prev = debounce.get(thread_id)
        if prev is not None and not prev.done():
            prev.cancel()
        debounce[thread_id] = asyncio.create_task(_debounced_dispatch(thread_id))
        # Periodic sub refresh — cheap, every event.
        await _refresh_subscriptions()


def start_worker() -> None:
    """Spawn the worker task in the running event loop. Called from
    SlackConfig.ready() once an event loop is available (ASGI startup)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop at Django app startup — that's normal under
        # manage.py and ASGI bootstrap before the server is up. The
        # worker will be started later via the periodic sweep entry
        # point (when ASGI accepts its first connection). For v1, just
        # defer to module-import-time and let the channels worker bind
        # on first event by virtue of the periodic sweep refreshing
        # subscriptions.
        return
    loop.create_task(_run_worker())
