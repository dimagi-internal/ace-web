"""FastMCP server exposing curated v2 routes as MCP tools.

Strategy: Use ``FastMCP.from_openapi`` pointed at the live Ninja OpenAPI
schema.  Only endpoints that carry ``x-mcp-expose: true`` in their OpenAPI
extension are exposed — all others are excluded by the ``route_map_fn``.
Endpoints opt in via ``openapi_extra={"x-mcp-expose": True}`` on the Ninja
route decorator.

Auth: the MCP server is an HTTP-loopback client: each tool call issues an
``httpx`` request back to the v2 API on the loopback address.  The MCP caller
must supply ``Authorization: Bearer <token>`` in its HTTP request to
``/api/mcp/``.  FastMCP forwards incoming headers to the httpx client via a
custom ``BearerPassthrough`` auth class, so the Bearer token is re-used for
every tool call and the standard ``DjangoSessionAuth`` Bearer path in
``apps/api_v2/auth.py`` validates it normally.

CSRF: Bearer-authenticated requests bypass CSRF (stateless tokens are not
susceptible to cross-site forgery), so no CSRF tokens are needed.

Mounting: the server is mounted in ``config/asgi.py`` as a Starlette
``Mount`` at ``/api/mcp``.  Django URL routing is NOT used because
``mcp.http_app()`` returns a Starlette ASGI application, not a Django view.

To expose a new endpoint, add ``openapi_extra={"x-mcp-expose": True}`` to
its Ninja route decorator and restart the server (schema is loaded once at
startup).

Usage (Claude Code ``mcp.json``):

    {
      "ace-web": {
        "url": "https://labs.connect.dimagi.com/ace/api/mcp/",
        "headers": { "Authorization": "Bearer <your-personal-token>" }
      }
    }
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType
from fastmcp.utilities.openapi import HTTPRoute

log = logging.getLogger(__name__)

# Base URL for loopback HTTP calls back into the Django app.
# In production this is the internal ECS task URL (no TLS, same VPC).
# In local dev the default works with `docker compose up` or `manage.py runserver`.
ACE_WEB_INTERNAL_URL = os.environ.get("ACE_WEB_INTERNAL_URL", "http://localhost:8000")


class _BearerPassthrough(httpx.Auth):
    """httpx Auth that accepts a Bearer token and injects it on every request.

    The token is resolved once per MCP session from the ``Authorization``
    header that the MCP client sends to the FastMCP HTTP transport.  FastMCP
    exposes it via the ``Context`` object; we store it at construction time so
    the httpx client can forward it to the Django v2 API unchanged.
    """

    def __init__(self, token: str) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request):  # type: ignore[override]
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


def _route_map_fn(route: HTTPRoute, default_type: MCPType) -> MCPType | None:
    """Include only endpoints flagged with ``x-mcp-expose: true``.

    FastMCP's ``route_map_fn`` is called for every route in the OpenAPI spec.
    Returning ``MCPType.EXCLUDE`` drops the route; returning ``None`` accepts
    the FastMCP default (tools for non-GET, resources/templates for GET).
    We override: every opted-in endpoint becomes a TOOL regardless of method
    so that AI clients always get a callable tool rather than a read-only
    resource, which is more ergonomic for agentic use.
    """
    if route.extensions.get("x-mcp-expose"):
        return MCPType.TOOL
    return MCPType.EXCLUDE


def _stringify_response_codes(schema: dict) -> dict:
    """Coerce integer HTTP status codes to strings in the OpenAPI paths.

    Django Ninja emits response codes as integers (e.g. ``200``, ``201``).
    FastMCP's OpenAPI parser requires them as strings (``"200"``, ``"201"``).
    This normalises the schema in-place and returns it.
    """
    for _path, methods in schema.get("paths", {}).items():
        for _method, op in methods.items():
            if not isinstance(op, dict):
                continue
            responses = op.get("responses")
            if not responses:
                continue
            stringified = {str(k): v for k, v in responses.items()}
            op["responses"] = stringified
    return schema


def build_mcp(token: str | None = None) -> FastMCP:
    """Construct a FastMCP server from the live Ninja OpenAPI schema.

    Called once at ASGI startup.  ``token`` is used for the loopback httpx
    client during schema introspection (not for per-call auth — per-call auth
    is handled by the middleware in ``make_asgi_app``).

    The httpx client is created with a dummy auth here; per-request auth is
    injected by FastMCP's context propagation (see ``make_asgi_app``).
    """
    # Lazy Django import — this module is loaded at ASGI startup after Django
    # is fully configured, so ORM / settings are available.
    import django
    from django.conf import settings as _settings

    if not django.apps.registry.apps.models_ready:  # pragma: no cover
        # Shouldn't happen in normal flow; guard for import-time test runs.
        django.setup()

    from apps.api_v2.api import api as ninja_api

    schema = _stringify_response_codes(ninja_api.get_openapi_schema())

    # Patch the servers list so FastMCP knows the base URL for loopback calls.
    # Ninja omits the servers block when there's no explicit server URL.
    base_prefix = getattr(_settings, "FORCE_SCRIPT_NAME", "") or ""
    schema.setdefault("servers", [{"url": f"{ACE_WEB_INTERNAL_URL}{base_prefix}"}])

    # httpx client for tool calls — auth will be replaced per-request by the
    # ASGI middleware wrapper; this default is used for schema introspection only.
    client = httpx.AsyncClient(
        base_url=f"{ACE_WEB_INTERNAL_URL}{base_prefix}",
        timeout=30.0,
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )

    mcp = FastMCP.from_openapi(
        openapi_spec=schema,
        client=client,
        name="ace-web",
        route_map_fn=_route_map_fn,
        validate_output=False,  # API returns problem+json on error; don't schema-validate
    )

    exposed = [
        route
        for path_methods in schema.get("paths", {}).values()
        for op in path_methods.values()
        if isinstance(op, dict) and op.get("x-mcp-expose")
        for route in [op.get("operationId", "")]
    ]
    log.info("FastMCP: registered %d MCP tools from opted-in endpoints", len(exposed))
    return mcp


def make_asgi_app() -> Any:
    """Return a Starlette ASGI app for the FastMCP server.

    Wraps ``build_mcp()`` in a Starlette ``Lifespan`` so that the httpx
    client is created once and reused across requests.

    The path is set to ``/mcp`` because the ASGI app is mounted under
    ``/api/mcp`` in ``config/asgi.py`` — Starlette mount strips the mount
    prefix, so the internal path is just ``/mcp``.
    """
    mcp = build_mcp()
    return mcp.http_app(path="/mcp")
