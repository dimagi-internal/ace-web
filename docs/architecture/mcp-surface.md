# MCP surface

ace-web exposes a curated set of v2 API endpoints as MCP tools at `/api/mcp/`,
so AI agents (Claude Code, OpenAI MCP clients, etc.) can call ace-web as
native tools rather than raw HTTP REST.

## How it works

The server is built with [FastMCP](https://gofastmcp.com/) using
`FastMCP.from_openapi`, pointed at the live Ninja OpenAPI schema.  Only
endpoints that opt in are exposed as tools; all others are excluded.  Tool
calls are HTTP-loopback: FastMCP issues an `httpx` request back to the v2
API on the loopback address, so auth, tenancy gating, and every other
middleware layer applies identically to REST callers.

## How an endpoint opts in

Add `openapi_extra={"x-mcp-expose": True}` to the Ninja route decorator:

```python
@router.get(
    "",
    response=Page[OppCardOut],
    summary="List opps in workspace",
    openapi_extra={"x-mcp-expose": True},
)
def list_opps(...):
    ...
```

The `route_map_fn` in `apps/api/mcp_server.py` checks
`route.extensions.get("x-mcp-expose")` and maps matching routes to
`MCPType.TOOL`; everything else is `MCPType.EXCLUDE`.  Restart the
server after adding the flag (schema is loaded once at ASGI startup).

## Auth model

MCP tools authenticate via Bearer tokens (`PersonalToken`).  The MCP client
provides `Authorization: Bearer <token>` in its HTTP request to `/api/mcp/`.
FastMCP's HTTP transport passes the header through to every loopback `httpx`
request via the `_BearerPassthrough` auth class, and the standard
`DjangoSessionAuth` Bearer path in `apps/api/auth.py` validates it
normally.

Per-call workspace membership and role checks still apply — the MCP tool
operates as the token's owner.

CSRF is not required for Bearer-authenticated requests (stateless tokens are
not susceptible to cross-site forgery).

## Endpoints currently exposed (9)

| Tool name | Method | Path | Summary |
|---|---|---|---|
| `apps_opps_api_list_opps` | GET | `/api/w/{workspace_slug}/opps` | List opps in workspace |
| `apps_opps_api_get_opp` | GET | `/api/w/{workspace_slug}/opps/{slug}` | Opp Workbench snapshot |
| `apps_opps_api_list_runs` | GET | `/api/w/{workspace_slug}/opps/{slug}/runs` | List runs for opp |
| `apps_opps_api_get_run` | GET | `/api/w/{workspace_slug}/opps/{slug}/runs/{run_id}` | Run detail |
| `apps_opps_api_get_step` | GET | `/api/w/{workspace_slug}/opps/{slug}/steps/{skill}` | Step detail |
| `apps_opps_api_get_artifact` | GET | `/api/w/{workspace_slug}/opps/{slug}/artifacts/{artifact_id}` | Artifact metadata |
| `apps_opps_api_get_scorecard` | GET | `/api/w/{workspace_slug}/opps/{slug}/scorecard` | Opp-eval scorecard |
| `apps_sessions_api_list_sessions` | GET | `/api/w/{workspace_slug}/sessions` | List sessions in workspace |
| `apps_sessions_api_get_session` | GET | `/api/w/{workspace_slug}/sessions/{slug}` | Session detail |

All are read-only.  Write actions (fork, gate decisions) are intentionally
kept manual for now; expose them by adding `openapi_extra={"x-mcp-expose": True}`
to the relevant decorator when ready.

## Connecting Claude Code

Add to `~/.claude/mcp.json` (or the equivalent for your MCP client):

```json
{
  "ace-web": {
    "url": "https://labs.connect.dimagi.com/ace/api/mcp/",
    "headers": { "Authorization": "Bearer <your-personal-token>" }
  }
}
```

Restart Claude Code.  The 9 opted-in endpoints appear as native tools.

To mint a personal token: Settings → Personal Tokens → New token (or `POST
/api/tokens/` with a session cookie).  The token resolves to your user and
respects your workspace memberships.

## Local dev

The MCP endpoint is available at `http://localhost:8000/api/mcp/` when the
app is running with `docker compose up`.  Use a personal token minted on the
local instance.

## Production exposure

The MCP endpoint is mounted at `/api/mcp/` in `config/asgi.py` as a
Starlette `Mount` wrapping the FastMCP ASGI app.  It sits behind the same
nginx sidecar + ALB stack as the rest of the API.  No additional network
exposure or auth weakening.

The `ACE_WEB_INTERNAL_URL` environment variable controls the loopback base
URL (default: `http://localhost:8000`).  In ECS, set it to `http://127.0.0.1:8000`
or the task's internal address.

## Key files

- `apps/api/mcp_server.py` — `build_mcp()`, `make_asgi_app()`,
  `_route_map_fn`, `_stringify_response_codes`, `_BearerPassthrough`
- `config/asgi.py` — Starlette `Mount("/api/mcp", app=_mcp_app)`
- `apps/api/tests/test_mcp_server.py` — unit tests for tool registration
  and filter logic
