"""Workspace-wide activity feed helpers.

The DRF ``activity_feed`` view was removed in the Phase 5 API
modernisation — all traffic now flows through the Ninja v2 router
(``apps/activity/api_v2.py``).  This module retains the pure helper
functions so that ``api_v2`` can import them without pulling in DRF.

Out-of-scope for v1:
  - Artifact mtimes (they'd require a per-opp file walk; skipped because
    every artifact already has a verdict so verdicts proxy them).
  - Real-time updates (the Timeline view re-fetches on tab focus).
"""
from __future__ import annotations

from django.core.cache import cache
from django.http import HttpRequest

from apps.opps.sync import list_opp_events_lean
from apps.sessions.models import Session
from apps.sessions.views import _scope_sessions_to_user

# Default cap so a noisy workspace doesn't dump thousands of events
# into a single response. Frontend renders by day; 200 events covers
# multiple days for a typical workspace.
DEFAULT_LIMIT = 200
MAX_LIMIT = 500

# Drive aggregation across a full workspace takes 30-60s the first
# time (one load_opp call per opp). Cache the result for 60s so
# subsequent loads — including the chat-only frontend that hits
# /api/activity/?type=chat first and then /api/activity/?type=verdict
# — return instantly from the warm cache.
DRIVE_CACHE_SECONDS = 60


def _chat_events(request: HttpRequest, workspace_slug: str, opp_slug: str | None) -> list[dict]:
    qs = _scope_sessions_to_user(Session.objects.all(), request.user)
    if opp_slug:
        qs = qs.filter(opp_slug=opp_slug)
    qs = qs.order_by("-created_at")[:DEFAULT_LIMIT]
    out: list[dict] = []
    for s in qs:
        out.append(
            {
                "kind": "chat",
                "ts": s.created_at.isoformat(),
                "opp_slug": s.opp_slug or None,
                "step_skill": s.opp_step_skill or None,
                "title": s.title or "Untitled",
                "session_slug": s.slug,
                "meta": {
                    "source": s.source,
                    "status": s.status,
                    "message_count": s.messages.count(),
                },
            }
        )
    return out


def _verdict_events_from_dict(verdicts_by_skill: dict, opp_slug: str) -> list[dict]:
    out: list[dict] = []
    for skill, v in verdicts_by_skill.items():
        if v is None or not v.evaluated_at:
            continue
        out.append(
            {
                "kind": "verdict",
                "ts": v.evaluated_at,
                "opp_slug": opp_slug,
                "step_skill": skill,
                "title": _verdict_title(v, skill),
                "meta": {"score": v.score, "passed": v.passed},
            }
        )
    return out


_FOLDER_MIME = "application/vnd.google-apps.folder"


def _drive_events_cached(
    workspace_slug: str,
    ace_folder_id: str,
    opp_slug: str | None,
    client,
) -> list[dict]:
    """Aggregate verdict events for the requested opp scope, with a
    60-second cache keyed by (workspace, opp).
    """
    key = f"activity:drive:{workspace_slug}:{opp_slug or '*'}"
    cached = cache.get(key)
    if cached is None:
        cached = []
        opp_slugs_in_scope = _opp_scope(client, ace_folder_id, opp_slug)
        for slug in opp_slugs_in_scope:
            try:
                # Lean per-opp scan — verdicts only, no recursive walk,
                # no pdd.md read, no manifest match.
                # See apps/opps/sync.py:list_opp_events_lean.
                verdicts = list_opp_events_lean(
                    client, ace_folder_id=ace_folder_id, slug=slug,
                )
            except Exception:
                # Drive listing failures shouldn't kill the whole feed;
                # the timeline degrades to "this opp's events are
                # missing" rather than 500.
                continue
            cached.extend(_verdict_events_from_dict(verdicts, slug))
        cache.set(key, cached, timeout=DRIVE_CACHE_SECONDS)
    return list(cached)


def _opp_scope(client, ace_folder_id: str, opp_slug: str | None) -> list[str]:
    """Return the opp slugs to iterate. If a specific opp is requested,
    just that one; otherwise every direct child folder of the ACE root."""
    if opp_slug:
        return [opp_slug]
    children = client.list_files(ace_folder_id) or []
    return [c.name for c in children if c.mime_type == _FOLDER_MIME]


def _verdict_title(v, skill: str) -> str:
    if v.passed is True:
        outcome = "PASS"
    elif v.passed is False:
        outcome = "FAIL"
    else:
        outcome = "scored"
    score_str = ""
    if v.score is not None:
        score_str = f" {v.score:g}/100" if v.score > 10 else f" {v.score:.1f}/10"
    return f"{outcome}{score_str} — {skill}"
