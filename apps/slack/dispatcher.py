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
from datetime import UTC, datetime

from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer

from .blocks import (
    parent_state_hash,
    phase_state_hash,
    render_parent_card,
    render_phase_tile,
)
from .blocks_decisions import (
    decisions_state_hash,
)
from .models import SlackRunThread
from .slack_client import SlackChannelGone, SlackRateLimited, client_for

logger = logging.getLogger(__name__)

# Sweep cadence. Tracked threads (laptop-driven runs) have no opp.updated
# push signal, so the sweep is their only progress source. 30s strikes a
# balance: each tick costs ~N × ~30ms (one Drive Changes poll per active
# thread); 30s gives the user reasonable freshness without thrashing.
_SWEEP_INTERVAL_SECONDS = 30


def _opp_group(slug: str, run_id: str) -> str:
    return f"opp.{slug}.{run_id or 'default'}"


def _load_snapshot(slug: str, workspace, run_id: str | None = None) -> dict | None:
    from apps.opps.api import load_rich_opp_snapshot
    snap = load_rich_opp_snapshot(workspace, slug, run_id=run_id)
    if snap is not None:
        opp = snap.get("opp") or {}
        if "display_name" not in snap:
            snap["display_name"] = opp.get("display_name", slug)
    return snap


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
    if thread.broken_at is not None or thread.stopped_at is not None:
        return

    from django.core.cache import cache
    lock_key = f"slack:dispatch:{thread.pk}"
    if not cache.add(lock_key, "held", timeout=5):
        return  # another worker is dispatching for this thread
    try:
        workspace = thread.installation.ace_workspace
        snapshot = _load_snapshot(thread.opp_slug, workspace, run_id=thread.run_id or None)
        if snapshot is None:
            logger.info("snapshot not yet available for %s/%s",
                        thread.opp_slug, thread.run_id)
            return

        client = _get_client(thread.installation)
        elapsed = int((datetime.now(UTC) - thread.triggered_at).total_seconds())
        phase_messages = dict(thread.phase_messages or {})

        all_decisions = snapshot.get("current_run", {}).get("decisions") or []

        # 1. Per-phase create / update
        for phase in snapshot.get("phases", []):
            pname = phase["name"]
            # Skip phases with no steps yet — nothing to render.
            steps_in_phase = [s for s in snapshot["current_run"]["steps"]
                              if s["phase"] == pname]
            if not steps_in_phase:
                continue

            existing = phase_messages.get(pname)
            phase_decisions = [d for d in all_decisions if d.get("phase") == pname]

            # Include decision state in the phase hash so new decisions
            # trigger a tile re-render.
            h = phase_state_hash(snapshot, pname)
            dh = decisions_state_hash(phase_decisions, {})
            combined_hash = f"{h}:{dh}"

            blocks = render_phase_tile(snapshot, phase_name=pname,
                                       opp_slug=thread.opp_slug,
                                       workspace_slug=workspace.slug)
            text = f"Phase {phase['ordinal']}: {phase['display_name']}"
            try:
                if existing is None:
                    ts = client.post_message(channel=thread.channel_id,
                                             blocks=blocks, text=text,
                                             thread_ts=thread.parent_ts)
                    phase_messages[pname] = {"ts": ts, "last_state_hash": combined_hash}
                elif existing.get("last_state_hash") != combined_hash:
                    client.update_message(channel=thread.channel_id,
                                          ts=existing["ts"],
                                          blocks=blocks, text=text)
                    existing["last_state_hash"] = combined_hash
                    phase_messages[pname] = existing
            except SlackChannelGone:
                thread.broken_at = datetime.now(UTC)
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
                thread_id=str(thread.pk),
            )
            try:
                client.update_message(channel=thread.channel_id, ts=thread.parent_ts,
                                      blocks=parent_blocks,
                                      text=f"ACE run · {thread.opp_slug}")
            except SlackChannelGone:
                thread.broken_at = datetime.now(UTC)
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
    """Belt-and-suspenders sweep. Every _SWEEP_INTERVAL_SECONDS, dispatch_tick
    every still-watched thread.

    For tracked (laptop-driven) runs this is the *only* progress signal —
    no opp.updated event fires for runs outside ace-web's turn_driver.
    For web-driven runs it catches missed pushes (worker restart, lost
    event). Threads with `broken_at` or `stopped_at` set are skipped."""
    while True:
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
        try:
            ids = await sync_to_async(list)(
                SlackRunThread.objects.filter(
                    broken_at__isnull=True, stopped_at__isnull=True,
                ).values_list("pk", flat=True)
            )
            for tid in ids:
                await sync_to_async(dispatch_tick)(thread_id=tid)
        except Exception:
            logger.exception("periodic sweep failed")


def _find_thread_pk(slug: str, run_id: str):
    """Sync helper for the async worker: thread pk for (slug, run_id) or None.

    Returns only active threads (neither broken nor stopped)."""
    return (
        SlackRunThread.objects.filter(
            opp_slug=slug, run_id=run_id,
            broken_at__isnull=True, stopped_at__isnull=True,
        )
        .values_list("pk", flat=True)
        .first()
    )


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
            SlackRunThread.objects.filter(broken_at__isnull=True, stopped_at__isnull=True)
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
        SlackRunThread.objects.filter(
            broken_at__isnull=True, stopped_at__isnull=True,
        ).values_list("pk", flat=True)
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
        thread_id = await sync_to_async(_find_thread_pk)(slug, run_id)
        if thread_id is None:
            continue
        # Coalesce: cancel any pending debounced dispatch for this thread.
        prev = debounce.get(thread_id)
        if prev is not None and not prev.done():
            prev.cancel()
        debounce[thread_id] = asyncio.create_task(_debounced_dispatch(thread_id))
        # Periodic sub refresh — cheap, every event.
        await _refresh_subscriptions()


async def run_worker_forever() -> None:
    """ASGI-lifespan entry point. Runs the Slack consumer worker.

    Called from config/asgi.py's lifespan context manager so the worker
    is spawned exactly when the ASGI app starts, with a running event
    loop, and is cancelled when the app shuts down.
    """
    try:
        await _run_worker()
    except asyncio.CancelledError:
        logger.info("slack worker cancelled at shutdown")
        raise
    except Exception:
        logger.exception("slack worker crashed; not restarted automatically")
