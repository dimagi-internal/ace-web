"""Workspace-wide activity feed for the Timeline view.

Aggregates events from two sources:

  1. Postgres — chats (Session creation timestamps; opp linkage carried
     via Session.opp_slug / opp_step_skill).
  2. Drive — per-opp verdict YAMLs (judge.evaluated_at).

Drive aggregation is the hot path: a workspace-wide call iterates every
opp in the workspace and calls ``load_opp`` for each. We rely on the
opps sync module's existing Drive client + structures rather than
re-implementing the listing here.

Out-of-scope for v1:
  - Artifact mtimes (they'd require a per-opp file walk; skipped because
    every artifact already has a verdict so verdicts proxy them).
  - Real-time updates (the Timeline view re-fetches on tab focus).
"""
from __future__ import annotations

from django.core.cache import cache
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.envelope import success_response
from apps.opps.sync import list_opp_events_lean
from apps.opps.views import (
    _require_drive,
    _resolve_ace_root_folder_id,
    _resolve_workspace,
)
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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def activity_feed(request: Request) -> Response:
    """Aggregate chats + verdicts as a single timeline.

    Query params:
      - ``opp``: limit to one opp slug (else all opps in the workspace
        the user is currently scoped to via X-ACE-Workspace).
      - ``type``: comma-separated list of event kinds to include.
        Default: all (``chat,verdict``).
      - ``limit``: max events to return (default 200, max 500).
    """
    opp_slug = request.query_params.get("opp", "").strip() or None
    requested_types = {
        t.strip()
        for t in request.query_params.get("type", "chat,verdict").split(",")
        if t.strip()
    }
    try:
        limit = max(1, min(MAX_LIMIT, int(request.query_params.get("limit", DEFAULT_LIMIT))))
    except ValueError:
        limit = DEFAULT_LIMIT

    needs_drive = "verdict" in requested_types

    # Workspace resolution is always required (membership gate); Drive
    # client creation only fires when verdicts are requested. This lets
    # the chat-only path work in environments where Drive isn't
    # configured (e.g. dev sandboxes, the test harness without
    # service-account fixtures).
    if needs_drive:
        ws, client, err = _require_drive(request)
        if err is not None:
            return err
    else:
        ws, err = _resolve_workspace(request)
        if err is not None:
            return err
        client = None

    events: list[dict] = []

    # 1. Chats from Postgres. Cheap, indexed, no Drive cost.
    if "chat" in requested_types:
        events.extend(_chat_events(request, ws.slug, opp_slug))

    # 2. Verdicts from Drive. Iterate the opp set in scope.
    if needs_drive:
        ace_folder_id = _resolve_ace_root_folder_id(ws)
        if ace_folder_id is not None and client is not None:
            drive_events = _drive_events_cached(
                ws.slug,
                ace_folder_id,
                opp_slug,
                client,
            )
            events.extend(drive_events)

    # Sort newest-first by ts (string ISO-8601 sorts lexically when
    # timestamps share format; everything we emit uses UTC ISO).
    events.sort(key=lambda e: e.get("ts", ""), reverse=True)
    events = events[:limit]

    return Response(success_response({"items": events, "total": len(events)}))


def _chat_events(request: Request, workspace_slug: str, opp_slug: str | None) -> list[dict]:
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
