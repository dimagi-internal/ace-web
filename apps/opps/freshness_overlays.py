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
overlay (``OppSnapshot.runs_summary``) = 1 extra Drive call per workbench
**detail** request. The list view's ``OppCard``s deliberately have NO
overlays — see "Where overlays live, and where they DON'T" below.

## Where overlays live, and where they DON'T

Overlays cost one Drive listing per cache hit. For a single workbench
**detail** request that's a rounding error against the 25-40 calls a cold
load fans out. For the Opps **list** view (N opps shown at once) it would be
``N × len(CARD_OVERLAYS)`` parallel Drive listings on every page render, and
the page render blocks on the slowest of them.

Concretely: PR #497 originally registered an ``OppCard.run_count`` overlay
alongside ``OppSnapshot.runs_summary``. On a 5-opp workspace this produced
5 parallel Drive listings per Opps-list page load — observed 8-12s page
loads (#510). PR #511 (this file) dropped the card overlay.

The trade we made when dropping it:

- ``OppCard.run_count`` is the count shown on each card in the Opps list.
- The Drive Changes API DOES correctly invalidate the underlying card cache
  when **existing** files inside ``<opp>/runs/`` are touched (e.g., a
  ``run_state.yaml`` update during an active run). So during normal use the
  count keeps updating.
- The count only goes stale when a brand-new run folder appears in Drive
  externally AND nobody has clicked into that opp's workbench since. The
  moment someone opens the workbench detail view, the ``runs_summary``
  overlay re-lists ``<opp>/runs/``, refreshes the snapshot, and the next
  Opps-list render shows the correct count.
- That's an acceptable staleness window for a card-level decorative count.
  It is NOT an acceptable staleness window for the workbench run-selector
  dropdown, which is why ``runs_summary`` keeps its overlay.

**Rule of thumb**: registry registration is not free. Overlays are
appropriate for fields visible to ONE opp at a time (workbench detail).
Overlays are inappropriate for fields visible to N opps at once (list
views, dashboards, activity timelines). Prefer the cached value over the
overlay whenever a field is rendered across N cached items per request.

## Adding a new overlay

When you find a new cached field that:

1. Is sourced from a Drive folder listing (not a file content read), AND
2. Gets externally appended to by orchestration / out-of-band writes, AND
3. Is visible to ONE cached item per request (workbench detail), not N

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


def _fetch_fresh_saved_overrides(
    client: Any, snapshot: Any, context: OverlayContext,
) -> Any:
    """Re-read ``<opp>/inputs/decision-overrides.yaml`` (issue #673 PR 2).

    The overrides file lives under ``inputs/`` — a listing the Changes
    API doesn't reliably invalidate when the file first appears — so a
    plain cached field would render freshly-saved overrides as
    AI-DEFAULT, which looks exactly like data loss.

    Uses the request's caching client as-is (NOT ``bypass=True`` like
    runs_summary): the 30s drive-cache TTL is acceptable staleness here,
    and ace-web's own save path writes through ``CachedDriveClient`` so
    its mutations invalidate these keys immediately.

    Returns a ``{"saved_overrides": {...}}`` wrapper so a legitimately
    empty result (file absent / all rows reverted) stays truthy and
    overwrites the cached value; transport failures raise and the
    overlay machinery preserves the cached value instead.
    """
    from apps.opps.decision_overrides import fetch_saved_overrides

    opp_folder_id = getattr(snapshot, "opp_folder_id", "")
    if not opp_folder_id:
        return None
    return {
        "saved_overrides": fetch_saved_overrides(
            client, opp_folder_id=opp_folder_id,
        ),
    }


def _apply_saved_overrides(snapshot: Any, fresh: dict[str, Any]) -> None:
    snapshot.saved_overrides = fresh["saved_overrides"]


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------


# Overlays for cached ``OppSnapshot`` payloads (load_opp_snapshot /
# load_rich_opp_snapshot). One Drive listing per workbench detail request.
SNAPSHOT_OVERLAYS: list[FreshnessOverlay] = [
    FreshnessOverlay(
        name="runs_summary",
        fetch_fn=_fetch_fresh_runs_summary,
        apply_fn=_apply_runs_summary,
    ),
    FreshnessOverlay(
        name="saved_overrides",
        fetch_fn=_fetch_fresh_saved_overrides,
        apply_fn=_apply_saved_overrides,
    ),
]


# Overlays for cached ``OppCard`` payloads (list_opp_cards). Deliberately
# EMPTY — see the module docstring's "Where overlays live, and where they
# DON'T" section. PR #497 originally registered ``OppCard.run_count`` here;
# #510 / #511 removed it because the list view renders N cards per request
# and N parallel Drive listings turned page load into an 8-12s wait. The
# card's ``run_count`` falls back to the cached value, which the Drive
# Changes API keeps roughly fresh during normal use (existing-file edits
# under ``<opp>/runs/`` invalidate the underlying snapshot). The only
# staleness path is "new run added externally + nobody has clicked into
# this opp's workbench since", which heals on the next workbench visit.
CARD_OVERLAYS: list[FreshnessOverlay] = []


# Default registry used by ``apply_freshness_overlays`` — kept for
# backwards-compat with callers that don't care which kind of snapshot
# they're holding. The function takes an explicit overlays list so
# snapshot-vs-card paths can pick the right registry.
OVERLAYS: list[FreshnessOverlay] = SNAPSHOT_OVERLAYS


# ---------------------------------------------------------------------------
# Resolved without an overlay — per-phase artifact lists
# ---------------------------------------------------------------------------
#
# Per-phase artifact lists (`<opp>/<phase-N>/`) and per-run phase folder
# listings (`<opp>/runs/<id>/<phase>/`) are externally-appendable Drive
# listings (orchestration writes new artifact files as it completes
# steps). An earlier draft of this module had them registered as a TODO
# for a future overlay; PR #575 obsoleted that approach.
#
# The original problem was that ``_build_steps`` in apps/opps/sync.py
# derived step status from artifact-file presence in those folders, so
# stale listings → stale step counts during live runs. PR #575 switched
# the primary source of truth to ``phases.<phase>.steps.<skill>.status``
# in the parsed run_state.yaml. The run_state file is a single existing
# file_id that the plugin patches at every step transition, the Drive
# Changes API reports edits to existing files reliably (unlike
# new-child-file additions), and so the OppSnapshot cache invalidates
# correctly on every step write. Artifact-presence stays as the
# fallback in ``_build_steps`` for legacy runs that pre-date the
# decisions-log era.
#
# Net effect: per-phase artifact listings can remain cached
# (Drive-blind-spot tolerated) without affecting live-progress freshness.
# An overlay here would have paid 10-30 Drive list calls on every cache
# hit; the run_state approach pays zero.
#
# See: docs/learnings/run-state-vs-artifact-presence.md
#      docs/learnings/drive-changes-api-parent-folder-blind-spot.md
#
# If a NEW user-visible staleness bug surfaces here that the run_state
# approach can't cover, open a follow-up issue rather than expanding
# this module's scope.


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
