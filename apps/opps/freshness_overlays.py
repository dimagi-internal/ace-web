"""Cache freshness-overlay registry for Drive-folder-listing-derived fields.

## The gotcha this exists to paper over

`apps/opps/snapshot_cache.py` is invalidated by file_ids reported via Google's
Drive Changes API. The Changes API reports newly-created files' own ids, but
**does not consistently report their parent folder's modifiedTime as
changed** when children are added externally (e.g. by orchestration running
on a different machine). The result: cached snapshots whose only signal that
something new exists is "the listing of folder X grew" never get invalidated,
because the new child's id isn't in any cached snapshot's tracked file_ids
and the parent folder's id (which IS tracked, see
``drive_cache.py``'s tracker.record(folder_id)) doesn't show up in the
changes feed either.

Symptom in production (#484): the workbench run-selector blinded itself to
runs created in Drive after the page first loaded. Same risk exists for every
field in a cached `OppSnapshot` / `OppCard` whose value is derived from a
**folder listing** of a folder that gets externally appended to.

## The fix

On every cache hit, re-list the relevant folders fresh (one Drive
``list_files`` per registered overlay) and overlay the result onto the cached
snapshot before returning. This preserves the long-lived content cache (the
content fetches the Changes API DOES invalidate correctly remain cached and
free) while keeping the cheap listings fresh.

Cost: ``len(OVERLAYS)`` Drive folder-listing calls per cache hit. Today: 1
overlay per registry = 1 extra Drive call per cache hit (`<opp>/runs/`).

## Adding a new overlay

When you find a new cached field that:

1. Is sourced from a Drive folder listing (not a file content read), AND
2. Gets externally appended to by orchestration / out-of-band writes

...register a `FreshnessOverlay` here. The overlay's `fetch_fn` should do
one Drive folder listing + parse + return the new field value. Failure
(Drive blip, missing folder) MUST preserve the cached value — never clobber
a perfectly good cached list with an empty list from a transient failure.

See ``docs/learnings/drive-changes-api-parent-folder-blind-spot.md`` for the
trade-off + history.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OverlayContext:
    """Per-request inputs an overlay needs beyond the cached snapshot itself.

    Carries the resolved ACE-root folder id and the opp slug so overlays
    can call into ``apps.opps.sync`` helpers (which are slug-keyed) without
    each overlay re-deriving them. Optional — overlays that don't need it
    simply ignore the argument.
    """

    ace_folder_id: str = ""
    slug: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FreshnessOverlay:
    """One listing-derived field that needs re-fetching on cache hit.

    Attributes:
        name: Human-readable label for logs (e.g. ``"runs_summary"``).
        fetch_fn: ``(client, snapshot, context) -> fresh_value``. Performs
            the Drive listing(s) and returns the new field value. Should
            do exactly one Drive folder ``list`` (the perf-guard test
            asserts this). Returning a falsy value signals "no data" /
            "Drive blipped" — preserves the cached value.
        apply_fn: ``(snapshot, fresh_value) -> None``. Mutates the
            snapshot in place. Called only when ``fetch_fn`` returned
            a truthy value.
    """

    name: str
    fetch_fn: Callable[[Any, Any, OverlayContext], Any]
    apply_fn: Callable[[Any, Any], None]

    def apply(self, snapshot: Any, client: Any, context: OverlayContext) -> None:
        """Run this overlay against ``snapshot`` using ``client`` + ``context``.

        Never raises. Drive failures, missing folders, or unexpected
        snapshot shapes log a warning and leave the cached value in
        place — matches #494's posture.
        """
        try:
            fresh = self.fetch_fn(client, snapshot, context)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "freshness overlay %s: fetch_fn failed: %s",
                self.name, exc,
            )
            return
        # Only overlay when we actually got something back. An empty
        # value from a transient Drive blip would clobber a perfectly
        # good cached value.
        if not fresh:
            return
        try:
            self.apply_fn(snapshot, fresh)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "freshness overlay %s: apply_fn failed: %s",
                self.name, exc,
            )


# ---------------------------------------------------------------------------
# Concrete overlays
# ---------------------------------------------------------------------------


def _fetch_fresh_runs_summary(client: Any, snapshot: Any, context: OverlayContext) -> Any:
    """Re-list ``<opp>/runs/`` and return the fresh ``RunSummary`` list.

    Beats the underlying ``CachedDriveClient`` TTL by wrapping the same
    inner client in a fresh ``CachedDriveClient(..., bypass=True)`` — reads
    go straight to Google. Without this, a sub-TTL refresh would return the
    same stale listing the snapshot was built from.
    """
    from apps.opps import snapshot_cache
    from apps.opps.sync import list_opp_runs

    if not context.ace_folder_id or not context.slug:
        return None
    fresh_client = snapshot_cache.cold_load_client(client)
    return list_opp_runs(
        fresh_client,
        ace_root_folder_id=context.ace_folder_id,
        opp_slug=context.slug,
    )


def _apply_runs_summary(snapshot: Any, fresh: list[Any]) -> None:
    snapshot.runs_summary = fresh


def _fetch_fresh_run_count(client: Any, card: Any, context: OverlayContext) -> Any:
    """Re-list ``<opp>/runs/`` and return the count of valid runs.

    "Valid" matches ``load_opp_card``'s definition: a run folder is only
    counted when it contains a ``run_state.yaml``. ``list_opp_runs``
    enforces that same gate (it skips run folders without
    ``run_state.yaml``), so its length is the canonical valid count and
    we reuse it here for free.

    Returns None when ``list_opp_runs`` returned an empty list — preserves
    the cached count (which might legitimately be 1 for a flat-layout
    opp) rather than overwriting with 0.
    """
    from apps.opps import snapshot_cache
    from apps.opps.sync import list_opp_runs

    if not context.ace_folder_id or not context.slug:
        return None
    fresh_client = snapshot_cache.cold_load_client(client)
    runs = list_opp_runs(
        fresh_client,
        ace_root_folder_id=context.ace_folder_id,
        opp_slug=context.slug,
    )
    if not runs:
        return None
    return len(runs)


def _apply_run_count(card: Any, fresh: int) -> None:
    card.run_count = fresh


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------


# Overlays for cached ``OppSnapshot`` payloads (load_opp_snapshot /
# load_rich_opp_snapshot).
SNAPSHOT_OVERLAYS: list[FreshnessOverlay] = [
    FreshnessOverlay(
        name="runs_summary",
        fetch_fn=_fetch_fresh_runs_summary,
        apply_fn=_apply_runs_summary,
    ),
]


# Overlays for cached ``OppCard`` payloads (list_opp_cards). Cards are
# narrower than snapshots — only the runs/-derived count needs refreshing
# today.
CARD_OVERLAYS: list[FreshnessOverlay] = [
    FreshnessOverlay(
        name="run_count",
        fetch_fn=_fetch_fresh_run_count,
        apply_fn=_apply_run_count,
    ),
]


# Default registry used by ``apply_freshness_overlays`` — kept for
# backwards-compat with callers that don't care which kind of snapshot
# they're holding. The function takes an explicit overlays list so
# snapshot-vs-card paths can pick the right registry.
OVERLAYS: list[FreshnessOverlay] = SNAPSHOT_OVERLAYS


# ---------------------------------------------------------------------------
# Out of scope — registered as TODOs for future overlays
# ---------------------------------------------------------------------------
#
# Per-phase artifact lists (`<opp>/<phase-N>/`) and per-run phase folder
# listings (`<opp>/runs/<id>/<phase>/`) are also externally-appendable
# Drive listings (orchestration writes new artifact files as it completes
# steps). They are NOT covered today because:
#
#   - Refreshing them requires re-walking the recursive opp tree + replaying
#     the manifest attribution machinery + re-reading every verdict file.
#     That's substantially more than "one Drive list call per overlay".
#   - In practice the workbench surfaces artifacts as part of the per-run
#     view, which a user re-selects when they want to see what's new. The
#     runs_summary overlay is sufficient to make the new run appear in the
#     dropdown; clicking it forces a cache miss for the new run_id and
#     fetches fresh.
#
# If a real user-visible staleness bug surfaces here, open a follow-up
# issue rather than expanding this PR's scope.


def apply_freshness_overlays(
    snapshot: Any,
    client: Any,
    *,
    context: OverlayContext | None = None,
    overlays: list[FreshnessOverlay] | None = None,
) -> Any:
    """Walk the registry and apply each overlay to ``snapshot``.

    Returns the same ``snapshot`` reference for caller convenience —
    overlays mutate in place. A single overlay failure preserves the
    cached value for that field and never aborts the rest of the walk;
    that's the deliberate posture from #494.

    ``overlays`` defaults to ``SNAPSHOT_OVERLAYS`` (back-compat). Pass
    ``CARD_OVERLAYS`` when applying to a cached ``OppCard``.

    ``context`` carries the per-request inputs (ACE root folder id, opp
    slug) overlays need to call into ``apps.opps.sync``. Omit it and
    overlays that depend on context will no-op.
    """
    if overlays is None:
        overlays = SNAPSHOT_OVERLAYS
    if context is None:
        context = OverlayContext()
    for overlay in overlays:
        overlay.apply(snapshot, client, context)
    return snapshot
