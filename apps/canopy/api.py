"""Django Ninja router for the apps.canopy identity-brokering surface.

ace-web's one remaining chat responsibility: exchange its registered
``AppCredential`` for a short-lived per-user delegated canopy token, and a
session-create wrapper that bakes in opp linkage. Everything else (session
list, messages, WS) is browser → canopy-web directly.
"""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest
from ninja import Router

from apps.api.auth import session_auth
from apps.api.errors import TYPE_UPSTREAM, ProblemError

from . import client
from .schemas import (
    CanopySessionCreateIn,
    CanopySessionCreateOut,
    CanopyStatusOut,
    CanopyTokenOut,
)

router = Router(auth=session_auth, tags=["canopy"])


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
        return client.exchange_token(request.user.email, ttl=3600)
    except client.CanopyError as exc:
        raise _upstream(exc) from exc


@router.post("/sessions", response={200: CanopySessionCreateOut})
def sessions(request: HttpRequest, body: CanopySessionCreateIn) -> dict:
    if not _enabled():
        raise ProblemError(503, "canopy hosted chat is not configured", type_=TYPE_UPSTREAM)

    metadata = {"source": "ace-web"}
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
