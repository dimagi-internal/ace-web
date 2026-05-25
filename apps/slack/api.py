"""Workspace-scoped Slack integration endpoints.

Powers three web surfaces that turn the Slack integration from "remember
the command" into "click a button":

- Workspace Settings panel — `GET /status` reports install state +
  installer + team URL so admins can see "is this thing on?" at a glance.
- Push-to-Slack action on PhaseView — `GET /channels` lists bot-member
  channels for the picker; `GET /push-info` reports any existing mirror
  threads for a (opp, run); `POST /push-phase` posts a parent card to a
  chosen channel and creates a `SlackRunThread` so subsequent updates
  flow through the existing mirror loop.

All endpoints live under `/api/w/<workspace_slug>/slack/`. Workspace
existence is hidden from non-members via the standard
`resolve_workspace_for_member` (404, not 403).
"""
from __future__ import annotations

import logging
from typing import Annotated

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from ninja import Path, Query, Router
from pydantic import BaseModel

from apps.api.auth import session_auth
from apps.api.deps import resolve_workspace_for_member
from apps.api.errors import (
    TYPE_CONFLICT,
    TYPE_NOT_FOUND,
    TYPE_VALIDATION,
    ProblemError,
)

from .blocks import render_parent_card, render_phase_tile
from .models import SlackInstallation, SlackRunThread
from .slack_client import SlackChannelGone, client_for

logger = logging.getLogger(__name__)

router = Router(auth=session_auth, tags=["slack"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SlackStatusOut(BaseModel):
    installed: bool
    team_id: str | None = None
    team_name: str | None = None
    team_url: str | None = None
    bot_user_id: str | None = None
    installed_by_email: str | None = None
    installed_at: str | None = None
    test_page_url: str | None = None
    install_url: str | None = None
    can_manage: bool = False
    # Live identity + scopes from Slack's auth.test (only populated when
    # ?debug=1 + caller can manage). Helps disambiguate "bot is in a
    # channel" vs "the bot in that channel isn't the bot ACE talks
    # through" vs "scope wasn't granted on reinstall".
    live_bot_id: str | None = None
    live_team: str | None = None
    live_url: str | None = None
    live_user: str | None = None
    granted_scopes: str | None = None


class SlackChannelOut(BaseModel):
    id: str
    name: str
    is_private: bool


class SlackChannelsOut(BaseModel):
    installed: bool
    channels: list[SlackChannelOut]
    # When Slack rejects conversations.list (e.g. missing_scope after a
    # bot scope was added but the install wasn't refreshed), surface
    # the raw Slack error code + a human-readable hint instead of
    # silently rendering an empty picker.
    error: str | None = None
    hint: str | None = None


class SlackThreadOut(BaseModel):
    channel_id: str
    parent_ts: str
    permalink: str | None
    stopped_at: str | None


class SlackPushInfoOut(BaseModel):
    installed: bool
    threads: list[SlackThreadOut]


class SlackPushPhaseIn(BaseModel):
    opp_slug: str
    run_id: str
    phase: str
    channel_id: str


class SlackPushPhaseOut(BaseModel):
    channel_id: str
    parent_ts: str
    permalink: str | None
    thread_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _can_manage(user) -> bool:
    """Mirror Nova's identity check — same write-permission policy."""
    from apps.common.auth_views import _can_write_global
    return _can_write_global(user)


def _installation_for(workspace) -> SlackInstallation | None:
    return SlackInstallation.objects.filter(ace_workspace=workspace).first()


def _install_url() -> str:
    base = getattr(
        settings, "ACE_PUBLIC_BASE_URL", "https://labs.connect.dimagi.com/ace",
    )
    return f"{base}/api/slack/install"


def _test_page_url() -> str:
    base = getattr(
        settings, "ACE_PUBLIC_BASE_URL", "https://labs.connect.dimagi.com/ace",
    )
    return f"{base}/api/slack/test/"


def _construct_permalink(team_url: str, channel_id: str, ts: str) -> str | None:
    """Fallback permalink when chat.getPermalink is unavailable.

    Slack permalinks are `<team_url>archives/<channel>/p<ts-no-dot>`. The
    canonical resolver is `chat.getPermalink`; use this only on failure.
    """
    if not team_url or not channel_id or not ts:
        return None
    ts_no_dot = ts.replace(".", "")
    base = team_url.rstrip("/")
    return f"{base}/archives/{channel_id}/p{ts_no_dot}"


# Process-wide cache of installation_pk → team_url. Slack `auth.test`
# is tier-3 (50/min) so this would be fine to call per-request, but
# requests cluster in bursts (settings page render, push-info polling),
# so cache it.
_TEAM_URL_CACHE: dict[str, str] = {}


def _ensure_team_url(installation: SlackInstallation) -> str:
    """Return the team URL, lazy-fetching via auth.test on first read.

    The team URL is needed to construct deep links into Slack. We don't
    store it on the model (no migration); cache by installation pk in
    process memory and re-fetch on cache miss.
    """
    key = str(installation.pk)
    cached = _TEAM_URL_CACHE.get(key)
    if cached:
        return cached
    try:
        data = client_for(installation).auth_test()
        url = data.get("url") or ""
    except Exception:
        logger.exception("auth_test failed for installation %s", installation.pk)
        url = ""
    if url:
        _TEAM_URL_CACHE[key] = url
    return url


def _load_snapshot(workspace, slug: str, run_id: str | None):
    from apps.opps.api import load_rich_opp_snapshot
    snap = load_rich_opp_snapshot(workspace, slug, run_id=run_id)
    if snap is not None:
        opp = snap.get("opp") or {}
        if "display_name" not in snap:
            snap["display_name"] = opp.get("display_name", slug)
    return snap


# ---------------------------------------------------------------------------
# GET /status — install status for the Workspace Settings panel
# ---------------------------------------------------------------------------


@router.get("/status", response={200: SlackStatusOut}, summary="Slack install status")
def get_status(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
) -> HttpResponse:
    ws = resolve_workspace_for_member(request, workspace_slug)
    installation = _installation_for(ws)
    can_manage = _can_manage(request.user)
    if installation is None:
        payload = SlackStatusOut(
            installed=False,
            install_url=_install_url() if can_manage else None,
            can_manage=can_manage,
        ).model_dump(mode="json", exclude_none=True)
        return JsonResponse(payload)
    team_url = _ensure_team_url(installation) or None
    installer_email = (
        installation.installed_by_user.email
        if installation.installed_by_user_id else None
    )
    debug = request.GET.get("debug") == "1" and can_manage
    live_fields: dict = {}
    if debug:
        # Call auth.test to confirm the token's identity + read
        # X-OAuth-Scopes from the response headers. Doesn't reach into
        # any private user data — just identity + scope list. Gated on
        # can_manage so random members can't enumerate.
        from slack_sdk.errors import SlackApiError
        try:
            web = client_for(installation)._web  # noqa: SLF001
            resp = web.auth_test()
            live_fields = {
                "live_bot_id": resp.data.get("bot_id"),
                "live_team": resp.data.get("team"),
                "live_url": resp.data.get("url"),
                "live_user": resp.data.get("user"),
                "granted_scopes": resp.headers.get("x-oauth-scopes")
                or resp.headers.get("X-OAuth-Scopes"),
            }
        except SlackApiError as e:
            live_fields = {
                "granted_scopes": (
                    f"auth.test FAILED: {e.response.get('error', 'unknown')}"
                ),
            }
    payload = SlackStatusOut(
        installed=True,
        team_id=installation.slack_team_id,
        team_name=installation.slack_team_name,
        team_url=team_url,
        bot_user_id=installation.bot_user_id,
        installed_by_email=installer_email,
        installed_at=installation.installed_at.isoformat(),
        test_page_url=_test_page_url(),
        install_url=_install_url() if can_manage else None,
        can_manage=can_manage,
        **live_fields,
    ).model_dump(mode="json", exclude_none=True)
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# GET /channels — bot-member channel picker source
# ---------------------------------------------------------------------------


@router.get("/channels", response={200: SlackChannelsOut}, summary="Bot-member channels")
def list_channels(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
) -> HttpResponse:
    from slack_sdk.errors import SlackApiError

    ws = resolve_workspace_for_member(request, workspace_slug)
    installation = _installation_for(ws)
    if installation is None:
        payload = SlackChannelsOut(
            installed=False, channels=[],
        ).model_dump(mode="json", exclude_none=True)
        return JsonResponse(payload)
    client = client_for(installation)
    try:
        channels = client.list_member_conversations()
    except SlackApiError as e:
        err = e.response.get("error", "slack_error")
        logger.warning(
            "list_member_conversations failed for ws=%s err=%s data=%s",
            ws.slug, err, dict(e.response.data) if hasattr(e.response, "data") else {},
        )
        hint = (
            "Slack rejected the channel list with `missing_scope` — the bot "
            "needs `channels:read` + `groups:read`. Reconnect from "
            "Workspace Settings → Slack to grant them."
            if err == "missing_scope"
            else f"Slack returned `{err}`. Check ace-web logs for details."
        )
        payload = SlackChannelsOut(
            installed=True, channels=[], error=err, hint=hint,
        ).model_dump(mode="json")
        return JsonResponse(payload)
    payload = SlackChannelsOut(
        installed=True,
        channels=[SlackChannelOut(**c) for c in channels],
    ).model_dump(mode="json", exclude_none=True)
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# GET /push-info — existing mirror threads for (opp, run)
# ---------------------------------------------------------------------------


@router.get(
    "/push-info",
    response={200: SlackPushInfoOut},
    summary="Existing Slack mirror threads for an opp/run",
)
def get_push_info(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    opp: Annotated[str, Query()],
    run: Annotated[str, Query()],
) -> HttpResponse:
    ws = resolve_workspace_for_member(request, workspace_slug)
    installation = _installation_for(ws)
    if installation is None:
        return JsonResponse(
            SlackPushInfoOut(installed=False, threads=[]).model_dump(mode="json"),
        )
    threads = SlackRunThread.objects.filter(
        installation=installation,
        opp_slug=opp,
        run_id=run,
        broken_at__isnull=True,
        stopped_at__isnull=True,
    ).order_by("-triggered_at")
    team_url = _ensure_team_url(installation)
    client = client_for(installation)
    out_threads: list[SlackThreadOut] = []
    for t in threads:
        permalink = client.get_permalink(channel=t.channel_id, message_ts=t.parent_ts)
        if not permalink:
            permalink = _construct_permalink(team_url, t.channel_id, t.parent_ts)
        out_threads.append(SlackThreadOut(
            channel_id=t.channel_id,
            parent_ts=t.parent_ts,
            permalink=permalink,
            stopped_at=t.stopped_at.isoformat() if t.stopped_at else None,
        ))
    payload = SlackPushInfoOut(
        installed=True, threads=out_threads,
    ).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# POST /push-phase — post parent + phase tile + create mirror thread
# ---------------------------------------------------------------------------


@router.post(
    "/push-phase",
    response={200: SlackPushPhaseOut},
    summary="Push a phase to a Slack channel and start mirroring",
)
def push_phase(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    body: SlackPushPhaseIn,
) -> HttpResponse:
    ws = resolve_workspace_for_member(request, workspace_slug)
    installation = _installation_for(ws)
    if installation is None:
        raise ProblemError(
            404, "Slack is not installed in this workspace", type_=TYPE_NOT_FOUND,
        )
    if not body.channel_id.strip():
        raise ProblemError(
            400, "channel_id is required", type_=TYPE_VALIDATION,
        )

    # Reject if this run is already being mirrored — frontend should be
    # showing "Tracked in #foo" instead. 409 keeps the contract explicit.
    existing = SlackRunThread.objects.filter(
        installation=installation,
        opp_slug=body.opp_slug,
        run_id=body.run_id,
        broken_at__isnull=True,
        stopped_at__isnull=True,
    ).first()
    if existing is not None and existing.channel_id == body.channel_id:
        raise ProblemError(
            409,
            f"Already mirroring {body.opp_slug}/{body.run_id} in this channel",
            type_=TYPE_CONFLICT,
        )

    snapshot = _load_snapshot(ws, body.opp_slug, body.run_id)
    if snapshot is None:
        raise ProblemError(
            404, f"Opp {body.opp_slug} not found", type_=TYPE_NOT_FOUND,
        )

    # Phase must exist in the snapshot — typo in URL etc. should surface
    # as a clean 400 rather than a Block Kit render exception.
    phase_names = {p.get("name") for p in (snapshot.get("phases") or [])}
    if body.phase not in phase_names:
        raise ProblemError(
            400, f"Phase {body.phase} not present in snapshot",
            type_=TYPE_VALIDATION,
        )

    client = client_for(installation)
    user = request.user
    triggerer_display = (
        f"{user.display_name or user.email}"
        if getattr(user, "display_name", None) or getattr(user, "email", None)
        else "ace-web"
    )
    parent_blocks = render_parent_card(
        snapshot,
        opp_slug=body.opp_slug,
        workspace_slug=ws.slug,
        triggerer_display=triggerer_display,
        elapsed_seconds=0,
    )
    try:
        parent_ts = client.post_message(
            channel=body.channel_id,
            blocks=parent_blocks,
            text=f"ACE run · {body.opp_slug}/{body.run_id}",
        )
    except SlackChannelGone as e:
        raise ProblemError(
            400,
            "ACE bot is not in that channel — invite it with /invite @ACE and retry.",
            type_=TYPE_VALIDATION,
        ) from e

    # Phase tile as a thread reply so the channel scroll stays compact.
    try:
        client.post_message(
            channel=body.channel_id,
            blocks=render_phase_tile(
                snapshot, phase_name=body.phase,
                opp_slug=body.opp_slug, workspace_slug=ws.slug,
            ),
            text=f"Phase: {body.phase}",
            thread_ts=parent_ts,
        )
    except Exception:
        # Tile is decoration; parent is the load-bearing record. Log
        # but don't fail the request — user already sees the parent.
        logger.exception(
            "push_phase tile post failed for %s/%s phase %s",
            body.opp_slug, body.run_id, body.phase,
        )

    thread = SlackRunThread.objects.create(
        installation=installation,
        channel_id=body.channel_id,
        parent_ts=parent_ts,
        opp_slug=body.opp_slug,
        run_id=body.run_id,
        ace_user=user,
        source="push",
    )
    permalink = client.get_permalink(channel=body.channel_id, message_ts=parent_ts)
    if not permalink:
        team_url = _ensure_team_url(installation)
        permalink = _construct_permalink(team_url, body.channel_id, parent_ts)
    payload = SlackPushPhaseOut(
        channel_id=body.channel_id,
        parent_ts=parent_ts,
        permalink=permalink,
        thread_id=str(thread.pk),
    ).model_dump(mode="json")
    return JsonResponse(payload)


__all__ = ["router"]
