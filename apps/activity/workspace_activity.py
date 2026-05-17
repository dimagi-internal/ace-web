"""Workspace Activity aggregator — 'what's running across the workspace right now?'

A single unified list of recently-touched runs, one row per opp's most
recent run. Used by both ace-web's Activity page and Slack's
`/ace activity` command.

Design principle: observable facts only. We don't claim what's "alive" —
just report what we observed in Drive + what ace-web Sessions exist.
See docs/specs/2026-05-16-workspace-activity-view-design.md.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import asdict, dataclass
from typing import Literal

from apps.opps.api import list_opp_cards
from apps.sessions.models import Session

logger = logging.getLogger(__name__)

# Window for "recent" rows. Anything completed within this window stays
# in the feed (faded); older completed runs are dropped.
_RECENT_WINDOW = dt.timedelta(hours=24)

# Default + max row counts. Slack caps tighter (handled at render time).
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


SourceHint = Literal["ace-web", "drive-only"]


@dataclass
class ActivityRow:
    """One row of the workspace activity feed.

    Every field is an observable fact — Drive content, ORM rows, or
    metadata lookups. NO inferred liveness claims (no `is_running`, no
    `is_alive`).
    """
    opp_slug: str
    opp_display_name: str
    run_id: str
    last_activity_at: str | None       # ISO-8601 from run_state.yaml modifiedTime
    current_phase_name: str | None
    current_phase_display: str | None
    current_step_name: str | None
    current_step_display: str | None
    lifecycle_status: str              # what run_state.yaml says
    last_actor: str | None             # plugin's self-reported actor
    source_hint: SourceHint
    source_actor_email: str | None
    phase_url: str

    def to_dict(self) -> dict:
        return asdict(self)


def detect_source(
    *, workspace, opp_slug: str, run_id: str
) -> tuple[SourceHint, str | None]:
    """Return (source_hint, actor_email).

    Looks for an active ace-web chat Session bound to (slug, run_id).
    If one exists, this is an ace-web-driven run (whoever owns that
    Session is the actor). Otherwise we can only say 'Drive only' —
    could be a laptop, a stranded session, an automation account.

    Workspace-scoped query so we don't leak across tenants if multiple
    Slack workspaces ever share opp slugs.
    """
    session = (
        Session.objects
        .filter(
            opp_slug=opp_slug,
            opp_run_id=run_id,
            workspace=workspace,
            status="active",
        )
        .select_related("owner")
        .order_by("-updated_at")
        .first()
    )
    if session is not None:
        actor = session.owner.email if session.owner_id else None
        return ("ace-web", actor)
    return ("drive-only", None)


def _parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        # Drive's modifiedTime is "2026-05-15T20:13:42.123Z" — normalize Z.
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def _public_base_url() -> str:
    from django.conf import settings
    return getattr(
        settings, "ACE_PUBLIC_BASE_URL",
        "https://labs.connect.dimagi.com/ace",
    )


def list_workspace_activity(
    workspace,
    *,
    include_completed: bool = True,
    limit: int = DEFAULT_LIMIT,
) -> list[ActivityRow]:
    """Return one ActivityRow per opp in the workspace, sorted by
    last_activity_at desc.

    Filtering:
      * Always include rows whose lifecycle_status != 'complete'.
      * If include_completed=True (default), also include rows whose
        lifecycle_status == 'complete' BUT last_activity_at is within
        the recent window.
      * If include_completed=False, drop all complete rows.

    Cost: one Drive snapshot read per workspace (cached) + one Session
    lookup per opp. Both are cheap on warm cache."""
    limit = min(max(limit, 1), MAX_LIMIT)

    cards = list_opp_cards(workspace)
    now = dt.datetime.now(dt.UTC)
    rows: list[ActivityRow] = []

    for c in cards:
        opp_slug = c.get("slug") or c.get("opp_slug")
        if not opp_slug:
            continue
        run_id = c.get("last_run_id") or ""
        if not run_id:
            # No runs yet — skip. Empty-state opps appear in /ace list opps,
            # not in Activity.
            continue
        # current_phase is set only for in-progress runs; for completed
        # runs the plugin clears it. So:
        #   has current_phase   → in_progress
        #   no current_phase    → the latest run finished (complete is
        #                         the practical default — we can't
        #                         distinguish qa-failed without reading
        #                         run_state.yaml per opp, which is too
        #                         expensive for the list view)
        # We already filtered out opps with no runs at all above, so a
        # missing current_phase HERE always means a finished run.
        current_phase = c.get("current_phase") or None
        current_step = c.get("current_skill") or c.get("current_step")
        lifecycle = "in_progress" if current_phase else "complete"

        # Recency filter.
        last_activity_iso = c.get("last_activity_at") or None
        last_activity_dt = _parse_iso(last_activity_iso)
        if lifecycle == "complete" and not include_completed:
            continue
        if (
            lifecycle == "complete"
            and last_activity_dt is not None
            and (now - last_activity_dt) > _RECENT_WINDOW
        ):
            continue

        source_hint, source_actor = detect_source(
            workspace=workspace, opp_slug=opp_slug, run_id=run_id,
        )

        phase_url = (
            f"{_public_base_url()}/w/{workspace.slug}/opps/{opp_slug}"
            f"?run_id={run_id}"
        )

        rows.append(ActivityRow(
            opp_slug=opp_slug,
            opp_display_name=c.get("title") or c.get("display_name") or opp_slug,
            run_id=run_id,
            last_activity_at=last_activity_iso,
            current_phase_name=current_phase,
            current_phase_display=c.get("current_phase_display"),
            current_step_name=current_step,
            current_step_display=c.get("current_step_display"),
            lifecycle_status=lifecycle,
            last_actor=c.get("last_actor"),
            source_hint=source_hint,
            source_actor_email=source_actor,
            phase_url=phase_url,
        ))

    # Sort by last_activity_at desc; rows without a timestamp sink to bottom.
    def _sort_key(r: ActivityRow) -> dt.datetime:
        parsed = _parse_iso(r.last_activity_at)
        return parsed or dt.datetime.min.replace(tzinfo=dt.UTC)

    rows.sort(key=_sort_key, reverse=True)
    return rows[:limit]
