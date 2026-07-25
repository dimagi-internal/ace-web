"""Django Ninja router for the apps.canopy identity-brokering surface.

ace-web's one remaining chat responsibility: exchange its registered
``AppCredential`` for a short-lived per-user delegated canopy token, and a
session-create wrapper that bakes in opp linkage. Everything else (session
list, messages, WS) is browser → canopy-web directly.

Session-create is mounted workspace-scoped (``/api/w/{workspace_slug}/canopy/
sessions``, alongside every other tenant-owned resource — see
``apps/sessions/api.py``) rather than taking a ``workspace_slug`` body field,
so it reuses the existing membership gate (``resolve_workspace_for_member``:
404s a non-member, never leaking whether the workspace exists) instead of
re-implementing it. ``origin_key`` is derived from that PATH parameter only —
never accepted from the request body — because canopy-web scopes its session
LIST by ``metadata.origin_key`` (see ``create_session`` below); if the caller
could set it, one ace workspace's user could stamp another workspace's key
and see its chats. ``status``/``token`` stay on the flat, non-workspace
``router`` since neither is workspace-specific (token exchange is per-user).
"""

from __future__ import annotations

from typing import Annotated

from django.conf import settings
from django.http import HttpRequest
from ninja import Path, Router

from apps.api.auth import session_auth
from apps.api.deps import resolve_workspace_for_member
from apps.api.errors import TYPE_UPSTREAM, ProblemError

from . import client
from .schemas import (
    CanopySessionCreateIn,
    CanopySessionCreateOut,
    CanopyStatusOut,
    CanopyTokenOut,
)

router = Router(auth=session_auth, tags=["canopy"])
# Workspace-scoped: mounted at /api/w/{workspace_slug}/canopy in apps/api/api.py.
workspace_router = Router(auth=session_auth, tags=["canopy"])


def _enabled() -> bool:
    return bool(settings.CANOPY_BASE_URL) and bool(settings.CANOPY_APP_CREDENTIAL)


def _upstream(exc: client.CanopyError) -> ProblemError:
    return ProblemError(
        exc.status if 400 <= exc.status < 600 else 502,
        "canopy-web request failed",
        type_=TYPE_UPSTREAM,
        detail="canopy-web is unavailable or rejected the request.",
    )


@router.get("/status", response={200: CanopyStatusOut})
def status(request: HttpRequest) -> dict:
    return {
        "enabled": _enabled(),
        "base_url": settings.CANOPY_PUBLIC_BASE_URL,
        "workspace": settings.CANOPY_WORKSPACE,
        "agent": settings.CANOPY_AGENT_SLUG,
    }


@router.post("/token", response={200: CanopyTokenOut})
def token(request: HttpRequest) -> dict:
    if not _enabled():
        raise ProblemError(503, "canopy hosted chat is not configured", type_=TYPE_UPSTREAM)
    try:
        exchanged = client.exchange_token(request.user.email, ttl=3600)
    except client.CanopyError as exc:
        raise _upstream(exc) from exc
    # Pick fields explicitly rather than passing canopy's raw dict through a
    # strict (extra="forbid") response schema — canopy adding a field to its
    # exchange response would otherwise 500 every token mint on this end
    # with no ace-web deploy involved (I4).
    return {"token": exchanged["token"], "expires_at": exchanged["expires_at"]}


@workspace_router.post("/sessions", response={200: CanopySessionCreateOut})
def sessions(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    body: CanopySessionCreateIn,
) -> dict:
    if not _enabled():
        raise ProblemError(503, "canopy hosted chat is not configured", type_=TYPE_UPSTREAM)

    # 404s a non-member without leaking whether the workspace exists — the
    # same gate every other tenant-scoped router uses.
    resolve_workspace_for_member(request, workspace_slug)

    # origin_key is derived from the resolved (and membership-checked) ace
    # workspace slug ONLY, never from the request body — this is what lets
    # canopy's session LIST (?origin_key=) scope to this one ace workspace
    # instead of every workspace sharing the same canopy tenant (C1).
    metadata = {"source": "ace-web", "origin_key": f"ace-web:{workspace_slug}"}
    if body.opp_slug:
        metadata["opp_slug"] = body.opp_slug
    if body.opp_run_id:
        metadata["opp_run_id"] = body.opp_run_id
    if body.opp_step_skill:
        metadata["opp_step_skill"] = body.opp_step_skill

    try:
        user_token = client.exchange_token(request.user.email, ttl=3600)
        result = client.create_session(user_token["token"], title=body.title, metadata=metadata)
    except client.CanopyError as exc:
        raise _upstream(exc) from exc
    return {"id": result["id"]}
