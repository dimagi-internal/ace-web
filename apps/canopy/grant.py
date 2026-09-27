"""The host grant: a canopy agent calling ace-web's MCP AS the visitor.

Host grant contract v1 (canopy-web ``docs/architecture/host-grant-contract.md``),
with every piece of crypto and every check from the canopy SDK (``canopy_sdk``).
The direction is the one that keeps canopy harmless: **ace-web issues the grant,
canopy only redeems it.**

1. When the SPA mints a canopy token (``POST /api/canopy/token?page=…``), the
   arrival carries an ID-JAG beside the visitor assertion — but only if the
   page is in ``PAGE_SCOPES`` below, and only with that page's scopes. The
   browser can say which page it is on; it can never say what that page grants.
2. canopy redeems it at ``/api/canopy/oauth/token`` (the SDK's jwt-bearer view:
   ``private_key_jwt`` + DPoP) for a short DPoP-bound token naming the visitor.
3. canopy calls ``/api/mcp/`` with ``Authorization: DPoP``. ``mcp_app`` below
   verifies the proof and resolves the token (the SDK's DPoP gate), the FastMCP
   middleware limits the session to ``SCOPE_TOOLS`` for its scopes, and each
   tool call runs through Django AS the visitor (``apps/api/auth.py`` reads
   ``current_delegation()``) — so every existing workspace-membership check
   applies, and the call is GET-only on top of that.

Everything is OFF until ``CANOPY_CLIENT_ID`` is set; until then no ID-JAG is
issued, the token endpoint refuses every grant, the metadata documents 404, and
the MCP app is exactly what it was.

The registries are the whole of what a delegated token can reach. Start
read-only; add a page only where "the agent may read what this person is
looking at, as them" is obviously fine.
"""
from __future__ import annotations

import contextvars
import logging

log = logging.getLogger(__name__)

# --- the registries --------------------------------------------------------------------

#: What each scope unlocks at ace-web's MCP. Tool names are the operationIds
#: FastMCP derives from the Ninja routes (apps/api/mcp_server.py). Read-only
#: opp Workbench reads, each membership-gated per workspace. Deliberately NOT
#: here: `apps_opps_api_seeded_run` (starts a run — a write), the session tools
#: (transcripts of other people's work), and the videos tools (not on a page
#: that has an agent pane).
SCOPE_TOOLS: dict[str, tuple[str, ...]] = {
    "opps:read": (
        "apps_opps_api_list_opps",
        "apps_opps_api_get_opp",
        "apps_opps_api_list_runs",
        "apps_opps_api_get_run",
        "apps_opps_api_get_step",
        "apps_opps_api_get_artifact",
        "apps_opps_api_get_scorecard",
    ),
}

#: Which pages grant which scopes. Keyed like the SDK's ``PAGE_SCOPES``; the
#: SDK validates it against ``SCOPE_TOOLS``.
PAGE_SCOPES: dict[str, tuple[str, ...]] = {
    # The opp Workbench — the page with the "Discuss in chat" pane. Everything
    # the agent can read here is what the visitor is already looking at.
    "opp-workbench": ("opps:read",),
}

#: How a page is recognised from the SPA's location (the WHOLE path must
#: match; ``/ace`` is the router basename, frontend/src/router.tsx). ace-web is
#: a single-page app: the server never renders a route, so it cannot sign a
#: page token. It uses the SDK's KEY mode instead (``PAGE_MODE = "key"`` in
#: ``config/canopy_host.py``, ``canopy_sdk.host.PageRegistry``): the browser
#: names its path, and the registry decides what, if anything, it grants — a
#: path can only SELECT among the read-only scopes registered here.
PAGE_PATTERNS: dict[str, str] = {
    "opp-workbench": r"(?:/ace)?/w/[^/]+/opps/(?!compare/)[^/]+(?:/runs/[^/]+(?:/steps/[^/]+)?)?/?",
}

#: Where the resolved principal rides on the MCP request's ASGI scope, from the
#: DPoP gate to the FastMCP middleware. Set only by ``mcp_app``; a client cannot
#: put anything on a scope.
PRINCIPAL_SCOPE_KEY = "canopy.delegated_principal"

_delegation: contextvars.ContextVar = contextvars.ContextVar("canopy_delegation", default=None)


# --- configuration -----------------------------------------------------------------------


def host_config():
    """The SDK's ``HostConfig`` for ace-web, or ``None`` when canopy is not
    configured here (no signing key, or one that does not load)."""
    from canopy_sdk.django import conf

    try:
        return conf.get_host_config()
    except Exception:  # noqa: BLE001 - HostNotConfigured, or a malformed key
        return None


def grant_enabled() -> bool:
    config = host_config()
    return bool(config and config.grant_enabled)


def subject_for(email: str) -> str:
    """ace-web's own id for a person: their lower-cased email. The visitor
    assertion has always carried it, so an ID-JAG names the same ``sub``."""
    return (email or "").strip().lower()


def subject_active(subject: str) -> bool:
    """SDK hook: is ``subject`` still a live ace-web account? Asked when a grant
    is redeemed and on every MCP call. Never creates anyone."""
    from django.contrib.auth import get_user_model

    if not subject:
        return False
    return get_user_model().objects.filter(email__iexact=subject, is_active=True).exists()


def page_key(path: str) -> str:
    """The registered page a SPA path is on, or ``""``."""
    from canopy_sdk.django import conf

    return conf.page_registry().key_for(path)


def scopes_for_page(path: str) -> tuple[str, ...]:
    """The scopes a page grants — from the registry, never from the request.
    ``()`` for an unregistered page, or while the grant is off."""
    from canopy_sdk.django import conf

    if not grant_enabled():
        return ()
    return tuple(conf.page_scopes(path, None))


# --- the MCP side ------------------------------------------------------------------------


def current_delegation():
    """The ``DelegatedPrincipal`` the current MCP tool call acts for, or ``None``.

    Set by ``DelegatedToolScope`` for exactly the duration of one tool call; the
    in-process request that call makes into Django inherits it. It is never set
    by anything a client sends, which is why ``apps/api/auth.py`` may trust it.
    """
    return _delegation.get()


def _publish_principal(app):
    """Copy the gate's verdict onto the ASGI scope, where it survives the hop
    from the HTTP request into FastMCP's session task (a context variable does
    not: the session runs in a task started by an earlier request)."""
    from canopy_sdk.host import delegated_principal

    async def inner(scope, receive, send):
        await app({**scope, PRINCIPAL_SCOPE_KEY: delegated_principal.get()}, receive, send)

    return inner


def mcp_app(app):
    """The MCP ASGI app behind the SDK's DPoP gate, installed unconditionally.

    A request with ``Authorization: DPoP`` must carry a valid proof and a live
    delegated token or it is refused at the gate — and while the grant is off
    (no ``CANOPY_CLIENT_ID``) every DPoP request is refused 401
    ``invalid_dpop_proof``, never a 500. Every other request (PATs) passes
    through untouched, with no principal.
    """
    from canopy_sdk.django.asgi import dpop_gate

    return dpop_gate(_publish_principal(app), require_principal=True)


def principal_of(request):
    """The delegated principal on an MCP HTTP request, or ``None``."""
    from canopy_sdk.host import DelegatedPrincipal

    scope = getattr(request, "scope", None)
    if not isinstance(scope, dict):
        return None
    principal = scope.get(PRINCIPAL_SCOPE_KEY)
    return principal if isinstance(principal, DelegatedPrincipal) else None


def _current_principal():
    from fastmcp.server.dependencies import get_http_request

    try:
        request = get_http_request()
    except RuntimeError:
        return None
    return principal_of(request)


def tool_scope_middleware():
    """FastMCP middleware limiting a delegated session to its scopes' tools."""
    from fastmcp.exceptions import ToolError
    from fastmcp.server.middleware import Middleware

    class DelegatedToolScope(Middleware):
        async def on_list_tools(self, context, call_next):
            tools = await call_next(context)
            principal = _current_principal()
            return principal.filter_tools(tools) if principal else tools

        async def on_call_tool(self, context, call_next):
            principal = _current_principal()
            if principal is None:
                return await call_next(context)
            name = context.message.name
            actor = ""
            try:
                from fastmcp.server.dependencies import get_http_request

                actor = get_http_request().headers.get("canopy-actor", "")[:100]
            except RuntimeError:
                pass
            if not principal.allows(name):
                log.warning("delegated MCP call refused: tool=%s sub=%s client=%s actor=%s",
                            name, principal.subject, principal.client_id, actor)
                # The same answer as a tool that does not exist: a delegated
                # session does not learn what else this server offers.
                raise ToolError(f"Unknown tool: {name}")
            log.info("delegated MCP call: tool=%s sub=%s act=%s client=%s actor=%s",
                     name, principal.subject, principal.actor, principal.client_id, actor)
            token = _delegation.set(principal)
            try:
                return await call_next(context)
            finally:
                _delegation.reset(token)

    return DelegatedToolScope()


# --- discovery (RFC 8414 / RFC 9728) -------------------------------------------------------


def _path_of(url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(url).path.rstrip("/")


def authorization_server_metadata(request, rest: str = ""):
    """``/.well-known/oauth-authorization-server{issuer path}`` — where canopy
    discovers our token endpoint. 404 while the grant is off: a server should
    not advertise a way in it does not offer."""
    from canopy_sdk.host import authorization_server_metadata as build
    from django.http import Http404, JsonResponse

    config = host_config()
    if not (config and config.grant_enabled):
        raise Http404
    if (rest or "").rstrip("/") != _path_of(config.issuer):
        raise Http404
    return JsonResponse(build(config))


def protected_resource_metadata(request, rest: str = ""):
    """``/.well-known/oauth-protected-resource{MCP path}`` (RFC 9728)."""
    from canopy_sdk.host import protected_resource_metadata as build
    from django.http import Http404, JsonResponse

    config = host_config()
    if not (config and config.grant_enabled):
        raise Http404
    if (rest or "").rstrip("/") != _path_of(config.resource):
        raise Http404
    return JsonResponse(build(config))
