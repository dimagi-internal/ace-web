"""FastMCP (3.x) server exposing curated v2 routes as MCP tools.

Strategy: Use ``FastMCP.from_openapi`` pointed at the live Ninja OpenAPI
schema.  Only endpoints that carry ``x-mcp-expose: true`` in their OpenAPI
extension are exposed — all others are excluded by the ``route_map_fn``.
Endpoints opt in via ``openapi_extra={"x-mcp-expose": True}`` on the Ninja
route decorator.

Transport: **Streamable HTTP**.  ``build_http_app()`` returns the
Streamable-HTTP ASGI app (``mcp.http_app(path="/", transport="streamable-http")``),
mounted in ``config/asgi.py`` with its session-manager lifespan wired in.

Execution model: **in-process, no network self-loopback**.  Each tool call
issues an ``httpx`` request whose transport is an ``httpx.ASGITransport``
bound directly to Django's ASGI application.  The request never leaves the
process — it is dispatched straight into Django's view stack — so there is no
TCP self-call to a localhost / internal URL.

Auth: **per-user passthrough**.  The MCP caller supplies
``Authorization: Bearer <token>`` on its HTTP request to ``/api/mcp/``.  FastMCP
exposes the live request via ``get_http_request()``; our ``_BearerPassthrough``
httpx auth reads the caller's ``Authorization`` header at request time and
re-injects it onto the in-process httpx request, so the standard
``DjangoSessionAuth`` Bearer path in ``apps/api/auth.py`` validates it and the
tool call runs AS that user.  (FastMCP 3.x's built-in OpenAPI header
forwarding via ``get_http_headers()`` deliberately strips ``authorization``,
which is why the explicit passthrough is still required.)

CSRF: Bearer-authenticated requests bypass CSRF (stateless tokens are not
susceptible to cross-site forgery), so no CSRF tokens are needed.

Mounting: ``build_http_app()`` returns a Starlette ASGI application, mounted in
``config/asgi.py`` as a Starlette ``Mount`` at ``<script_name>/api/mcp`` (the
``/ace`` prefix is preserved on connect-labs).  Django URL routing is NOT used
because the MCP app is not a Django view.

To expose a new endpoint, add ``openapi_extra={"x-mcp-expose": True}`` to its
Ninja route decorator and restart the server (schema is loaded once at
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
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.providers.openapi import MCPType
from fastmcp.utilities.openapi import HTTPRoute

log = logging.getLogger(__name__)

# The in-process httpx client dispatches straight into Django via
# ASGITransport — there is no real network address.  The URL host segment is
# still subject to Django's ``ALLOWED_HOSTS`` validation (CommonMiddleware
# calls ``request.get_host()``), so the host must be one Django accepts or the
# request 400s before it ever reaches a view.  ``_inprocess_host()`` resolves a
# concrete allowed host at client-build time (see below); this constant is the
# scheme-only prefix.
_INPROCESS_SCHEME = "http"


class _BearerPassthrough(httpx.Auth):
    """httpx Auth that forwards the *current* MCP caller's Bearer token.

    Unlike the old (fastmcp 0.4) design — which captured a single token at
    construction time — this reads the live HTTP request on every outgoing
    call via ``get_http_request()``.  That is required by the in-process
    model: the httpx client (and therefore this auth object) is built ONCE at
    ASGI startup and reused across every MCP session, so the token cannot be
    baked in.  Reading per-request keeps each tool call scoped to the caller
    that triggered it.

    FastMCP 3.x's built-in OpenAPI forwarding (``get_http_headers()``) strips
    ``authorization`` by default, so without this the caller's bearer would
    never reach Django and every tool call would 401.
    """

    def auth_flow(self, request: httpx.Request):  # type: ignore[override]
        token = self._current_bearer()
        if token:
            request.headers["Authorization"] = f"Bearer {token}"
        yield request

    @staticmethod
    def _current_bearer() -> str | None:
        """Return the Bearer token from the active MCP HTTP request, if any.

        ``get_http_request()`` raises (or there is simply no active request)
        outside of a live Streamable-HTTP request — e.g. during schema
        introspection or in unit tests.  In that case we return ``None`` and
        the downstream call goes out unauthenticated (Django answers 401),
        which is the correct behavior for an anonymous/contextless call.
        """
        try:
            request = get_http_request()
        except RuntimeError:
            return None
        if request is None:
            return None
        auth_header = request.headers.get("authorization") or request.headers.get(
            "Authorization"
        )
        if auth_header and auth_header.lower().startswith("bearer "):
            return auth_header[len("bearer "):].strip()
        return None


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


def _inprocess_host() -> str:
    """Pick a Host that Django's ALLOWED_HOSTS validation will accept.

    Even an in-process ASGITransport request goes through CommonMiddleware,
    which calls ``request.get_host()`` and validates it against
    ``ALLOWED_HOSTS``.  A bogus host 400s before the view runs.  We resolve a
    concrete allowed host here:

      * ``["*"]`` (dev) → any host is fine; use ``localhost``.
      * a list with concrete entries → use the first non-wildcard, non-pattern
        entry (skipping leading-dot subdomain wildcards like ``.example.com``).
      * empty / only-wildcards → fall back to ``localhost`` (also covers the
        test settings, which list ``localhost``).
    """
    from django.conf import settings as _settings

    allowed = list(getattr(_settings, "ALLOWED_HOSTS", []) or [])
    for host in allowed:
        if host and host != "*" and not host.startswith("."):
            return host
    return "localhost"


def _build_inprocess_client() -> httpx.AsyncClient:
    """Build an httpx client that dispatches in-process into Django.

    The transport is an ``httpx.ASGITransport`` bound to Django's ASGI
    application, so tool-call requests execute through Django's full middleware
    + view stack WITHOUT a TCP round-trip back to a localhost / internal URL.
    The caller's Bearer token is forwarded per-request by ``_BearerPassthrough``.
    """
    # Lazy Django import — this module is loaded at ASGI startup after Django
    # is fully configured, so ORM / settings are available.
    import django

    if not django.apps.registry.apps.models_ready:  # pragma: no cover
        # Shouldn't happen in normal flow; guard for import-time test runs.
        django.setup()

    from django.core.asgi import get_asgi_application

    django_asgi_app = get_asgi_application()

    # ``raise_app_exceptions=False`` so a 4xx/5xx from a view comes back as an
    # HTTP response (which FastMCP surfaces as a tool error) rather than
    # bubbling a Python exception out of the transport.
    transport = httpx.ASGITransport(app=django_asgi_app, raise_app_exceptions=False)
    return httpx.AsyncClient(
        transport=transport,
        base_url=f"{_INPROCESS_SCHEME}://{_inprocess_host()}",
        timeout=30.0,
        auth=_BearerPassthrough(),
    )


def build_mcp() -> FastMCP:
    """Construct a FastMCP server from the live Ninja OpenAPI schema.

    Called once at ASGI startup.  The httpx client uses an in-process ASGI
    transport (no network loopback); per-call auth is the caller's forwarded
    Bearer token (see ``_BearerPassthrough``).
    """
    # Lazy Django import — same rationale as ``_build_inprocess_client``.
    import django

    if not django.apps.registry.apps.models_ready:  # pragma: no cover
        django.setup()

    from apps.api.api import api as ninja_api

    schema = _stringify_response_codes(ninja_api.get_openapi_schema())

    # The schema's paths are absolute (`/api/...`) and the in-process transport
    # dispatches straight into Django's URLconf, which expects exactly those
    # paths (FORCE_SCRIPT_NAME affects URL *generation*, not in-process
    # routing).  So the client base_url carries no path prefix.
    client = _build_inprocess_client()
    schema.setdefault("servers", [{"url": str(client.base_url)}])

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


# Built once at import time (i.e. at ASGI startup, after Django is configured).
mcp = build_mcp()


def build_http_app() -> Any:
    """Return the Streamable-HTTP ASGI app for mounting at ``/api/mcp/``.

    ``path="/"`` because ``config/asgi.py`` mounts this app under the
    ``<script_name>/api/mcp`` prefix; the MCP endpoint then lives at
    ``/api/mcp/`` locally and ``/ace/api/mcp/`` on connect-labs.
    """
    return mcp.http_app(path="/", transport="streamable-http")
