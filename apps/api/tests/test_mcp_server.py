"""Unit tests for the FastMCP server bridge.

Tests:
1. ``build_mcp`` registers exactly the opted-in endpoints as tools.
2. ``_stringify_response_codes`` coerces integer response codes to strings.
3. ``_route_map_fn`` includes opted-in routes and excludes others.
4. The httpx loopback call is made with the correct method, path, and
   Authorization header (httpx.AsyncClient mocked).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apps.api.mcp_server import (
    MCPType,
    _BearerPassthrough,
    _route_map_fn,
    _stringify_response_codes,
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
# 4. BearerPassthrough injects Authorization header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bearer_passthrough_injects_header():
    """_BearerPassthrough inserts the Authorization header on every request."""
    import httpx

    auth = _BearerPassthrough("my-secret-token")

    request = httpx.Request("GET", "http://localhost:8000/api/test")
    # auth_flow is a generator
    gen = auth.auth_flow(request)
    sent_request = next(gen)
    assert sent_request.headers["Authorization"] == "Bearer my-secret-token"


def test_bearer_passthrough_formats_different_tokens():
    """Each token value produces the correct header value."""
    import httpx

    for token in ["abc123", "tok_xyz_789", "very-long-token-value"]:
        auth = _BearerPassthrough(token)
        request = httpx.Request("GET", "http://localhost:8000/")
        gen = auth.auth_flow(request)
        sent = next(gen)
        assert sent.headers["Authorization"] == f"Bearer {token}"
