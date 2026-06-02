"""Unit tests for the FastMCP server bridge (FastMCP 3.x, in-process).

Tests:
1. ``build_mcp`` registers exactly the opted-in endpoints as tools.
2. ``_stringify_response_codes`` coerces integer response codes to strings.
3. ``_route_map_fn`` includes opted-in routes and excludes others.
4. ``_BearerPassthrough`` forwards the current request's Bearer token (and is
   a no-op when there is no active request).
5. ``build_http_app`` builds a Streamable-HTTP ASGI app with a lifespan.
6. End-to-end through the in-process ASGITransport: an unauthenticated tool
   call is rejected (401) while a forwarded Bearer token authenticates as the
   token's user.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from apps.api.mcp_server import (
    MCPType,
    _BearerPassthrough,
    _build_inprocess_client,
    _route_map_fn,
    _stringify_response_codes,
    build_http_app,
    build_mcp,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXPECTED_TOOL_NAMES = {
    "apps_opps_api_list_opps",
    "apps_opps_api_get_opp",
    "apps_opps_api_list_runs",
    "apps_opps_api_get_run",
    "apps_opps_api_get_step",
    "apps_opps_api_get_artifact",
    "apps_opps_api_get_scorecard",
    "apps_opps_api_seeded_run",
    "apps_sessions_api_list_sessions",
    "apps_sessions_api_get_session",
    "apps_videos_api_list_programs",
    "apps_videos_api_get_program",
    "apps_videos_api_get_run",
    "apps_videos_api_get_library",
    "apps_videos_api_get_render_status",
    "apps_videos_api_get_render_log",
    "apps_videos_api_get_feedback",
    "apps_videos_api_list_video_templates",
    "apps_videos_api_get_video_template",
    "apps_videos_api_list_media_library_video",
    "apps_videos_api_list_media_library_audio",
}


# ---------------------------------------------------------------------------
# 1. Tool registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_mcp_registers_expected_tools():
    """build_mcp() should register each opted-in endpoint as an MCP tool."""
    mcp = build_mcp()
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    assert tool_names == _EXPECTED_TOOL_NAMES, (
        f"Unexpected tools. Extra: {tool_names - _EXPECTED_TOOL_NAMES}, "
        f"Missing: {_EXPECTED_TOOL_NAMES - tool_names}"
    )


@pytest.mark.asyncio
async def test_build_mcp_tools_have_descriptions():
    """All registered tools should have non-empty descriptions."""
    mcp = build_mcp()
    tools = await mcp.list_tools()
    for tool in tools:
        assert tool.description, f"Tool {tool.name!r} is missing a description"


# ---------------------------------------------------------------------------
# 2. Schema normalisation
# ---------------------------------------------------------------------------


def test_stringify_response_codes_converts_ints():
    """_stringify_response_codes converts integer response keys to strings."""
    schema = {
        "paths": {
            "/foo": {
                "get": {
                    "responses": {
                        200: {"description": "OK"},
                        404: {"description": "Not Found"},
                    }
                }
            }
        }
    }
    result = _stringify_response_codes(schema)
    responses = result["paths"]["/foo"]["get"]["responses"]
    assert "200" in responses
    assert "404" in responses
    assert 200 not in responses
    assert 404 not in responses


def test_stringify_response_codes_leaves_strings_alone():
    """Pre-stringified codes are preserved without duplication."""
    schema = {
        "paths": {
            "/bar": {
                "post": {
                    "responses": {
                        "201": {"description": "Created"},
                    }
                }
            }
        }
    }
    result = _stringify_response_codes(schema)
    responses = result["paths"]["/bar"]["post"]["responses"]
    assert "201" in responses
    assert 201 not in responses


def test_stringify_response_codes_handles_empty_paths():
    """An empty paths block is handled without error."""
    schema = {"paths": {}}
    result = _stringify_response_codes(schema)
    assert result["paths"] == {}


# ---------------------------------------------------------------------------
# 3. route_map_fn filtering
# ---------------------------------------------------------------------------


def _make_route(extensions: dict) -> MagicMock:
    """Create a minimal HTTPRoute-like mock with the given extensions."""
    route = MagicMock()
    route.extensions = extensions
    return route


def test_route_map_fn_includes_opted_in_routes():
    """Routes with x-mcp-expose=True map to TOOL."""
    route = _make_route({"x-mcp-expose": True})
    result = _route_map_fn(route, MCPType.TOOL)
    assert result == MCPType.TOOL


def test_route_map_fn_excludes_non_opted_in_routes():
    """Routes without x-mcp-expose map to EXCLUDE."""
    route = _make_route({})
    result = _route_map_fn(route, MCPType.TOOL)
    assert result == MCPType.EXCLUDE


def test_route_map_fn_excludes_falsy_expose_flag():
    """x-mcp-expose: False (or 0) is treated as not opted in."""
    for falsy in [False, 0, None, ""]:
        route = _make_route({"x-mcp-expose": falsy})
        result = _route_map_fn(route, MCPType.TOOL)
        assert result == MCPType.EXCLUDE, f"Expected EXCLUDE for x-mcp-expose={falsy!r}"


# ---------------------------------------------------------------------------
# 4. _BearerPassthrough forwards the current request's token
# ---------------------------------------------------------------------------


def test_bearer_passthrough_no_active_request_is_noop():
    """Outside a live HTTP request, no Authorization header is injected.

    ``get_http_request()`` has no active request here, so the passthrough must
    leave the outgoing request unauthenticated (Django then answers 401).
    """
    auth = _BearerPassthrough()
    request = httpx.Request("GET", "http://ace-web.internal/api/test")
    sent = next(auth.auth_flow(request))
    assert "Authorization" not in sent.headers


def test_bearer_passthrough_forwards_current_request_token():
    """When an MCP request carries a Bearer token, it is re-injected."""
    fake_request = MagicMock()
    fake_request.headers = {"authorization": "Bearer my-secret-token"}

    with patch(
        "apps.api.mcp_server.get_http_request", return_value=fake_request
    ):
        auth = _BearerPassthrough()
        request = httpx.Request("GET", "http://ace-web.internal/api/test")
        sent = next(auth.auth_flow(request))
        assert sent.headers["Authorization"] == "Bearer my-secret-token"


def test_bearer_passthrough_ignores_non_bearer_scheme():
    """A non-Bearer Authorization header is not forwarded."""
    fake_request = MagicMock()
    fake_request.headers = {"authorization": "Basic abc123"}

    with patch(
        "apps.api.mcp_server.get_http_request", return_value=fake_request
    ):
        auth = _BearerPassthrough()
        request = httpx.Request("GET", "http://ace-web.internal/api/test")
        sent = next(auth.auth_flow(request))
        assert "Authorization" not in sent.headers


# ---------------------------------------------------------------------------
# 5. Streamable-HTTP app builds with a lifespan
# ---------------------------------------------------------------------------


def test_build_http_app_has_lifespan():
    """build_http_app() returns a Streamable-HTTP ASGI app with a lifespan."""
    app = build_http_app()
    assert hasattr(app, "lifespan"), "MCP app must expose a lifespan for Streamable-HTTP"
    # Starlette ASGI app is callable.
    assert callable(app)


# ---------------------------------------------------------------------------
# 6. In-process transport: auth enforced per-user
# ---------------------------------------------------------------------------


# transaction=True: the in-process ASGITransport call runs through Django on a
# separate DB connection, so rows it commits escape the default rollback. Flush
# semantics clean them up and prevent leaking users into order-dependent tests
# (apps/auth, apps/workspaces).
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_inprocess_unauthenticated_call_rejected():
    """An in-process call with no forwarded Bearer is rejected by Django (401).

    With no active MCP request, ``_BearerPassthrough`` injects nothing, so the
    request reaches an ``auth=session_auth`` endpoint anonymously and gets the
    problem+json 401.
    """
    client = _build_inprocess_client()
    try:
        resp = await client.get("/api/_auth_smoke/")
    finally:
        await client.aclose()
    assert resp.status_code == 401
    assert resp.json()["title"] == "Authentication required"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_inprocess_forwarded_bearer_authenticates():
    """A forwarded Bearer token authenticates the in-process call as its user.

    Mints a real PersonalToken, fakes the active MCP request so
    ``_BearerPassthrough`` forwards that token, then hits an auth-gated
    endpoint and asserts a 200 (i.e. ``DjangoSessionAuth`` validated the
    forwarded bearer).
    """
    from asgiref.sync import sync_to_async
    from django.contrib.auth import get_user_model

    from apps.auth.models import PersonalToken

    User = get_user_model()
    user = await sync_to_async(User.objects.create_user)(
        email="mcp@example.com", display_name="MCP Test User"
    )
    raw, _token = await sync_to_async(PersonalToken.create_for_user)(
        user=user, label="mcp-test"
    )

    fake_request = MagicMock()
    fake_request.headers = {"authorization": f"Bearer {raw}"}

    client = _build_inprocess_client()
    try:
        with patch(
            "apps.api.mcp_server.get_http_request", return_value=fake_request
        ):
            resp = await client.get("/api/_auth_smoke/")
    finally:
        await client.aclose()

    assert resp.status_code == 200, resp.text
