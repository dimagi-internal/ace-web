# Learning: Nova MCP OAuth wiring (commcare.app)

**Date**: 2026-05-02
**Context**: Wiring the Nova plugin's HTTP MCP server (`https://mcp.commcare.app/mcp`) so `claude -p` subprocesses spawned by `CLIBackend` can call `mcp__plugin_nova_nova__*` tools without the interactive OAuth flow that's normally required. Spans PRs #173 (OAuth foundation), #174 (first-attempt headersHelper, superseded), #179 (env-var simplification), #180 (bot-perms alignment), #183 (concurrent-refresh lock).
**Status**: Active — read this before touching `apps/common/nova_auth_flow.py`, `apps/auth/nova_oauth_views.py`, the bundled Nova plugin's `.mcp.json` rewrite in the Dockerfile, or adding any other OAuth-protected MCP server.

## Problem

Nova requires OAuth 2.1 + PKCE per the late-2025 MCP spec. On a developer's laptop, Claude Code's MCP client handles the dance interactively (browser pop-up, click Allow). That doesn't work in a headless container, so ace-web has to:

1. Run the OAuth dance itself (server-side) and stash the resulting blob.
2. Inject a fresh access_token into every `claude -p` subprocess so the bundled plugin's HTTP MCP can authenticate without prompting.

Several non-obvious traps tripped us along the way; this doc captures them so the next OAuth-protected MCP integration doesn't re-derive them.

## Trap 1: RFC 8707 `resource` indicator is mandatory

Without `resource=https://mcp.commcare.app/mcp` on **both** `/authorize` and `/token`, commcare.app issues a 32-char opaque token. The MCP server then rejects it with `401 "no token payload"` because it expects an audience-bound JWT.

With the `resource` parameter, the AS issues a 650-char EdDSA JWT whose `aud` claim names the MCP resource. Server accepts.

Symptom is misleading — looks like an auth failure, is actually an audience-binding failure.

```python
# apps/common/nova_auth_flow.py
def authorize_url() -> str: return f"{issuer()}/oauth2/authorize"
def token_url()     -> str: return f"{issuer()}/oauth2/token"
def resource()      -> str: return "https://mcp.commcare.app/mcp"

# Both authorize redirect and token exchange POSTs MUST include:
params["resource"] = resource()
```

## Trap 2: env-var expansion in `.mcp.json` headers beats `headersHelper`

Claude Code's `.mcp.json` HTTP transport supports two ways to inject auth headers:

- **Static `headers` map** — useful for fixed API keys, useless for short-lived tokens.
- **`headersHelper`** — a script invoked at MCP-connect time; stdout JSON gets merged into headers.
- **`${VAR:-}` expansion inside `headers`** — substituted from the spawn env at MCP-connect time.

We initially shipped `headersHelper: "cd /app && python manage.py nova_headers"` (#174) — works but pays ~1s of Django startup per chat turn for a subprocess that does ~50ms of real work. Then realized env-var expansion gives the same freshness guarantee for free (#179):

```json
// /app/vendor/nova-plugin/.mcp.json (Dockerfile rewrites the plugin's bundled file)
{
  "mcpServers": {
    "nova": {
      "type": "http",
      "url": "https://mcp.commcare.app/mcp",
      "headers": { "Authorization": "Bearer ${NOVA_BEARER_TOKEN:-}" }
    }
  }
}
```

```python
# apps/common/cli_backend.py — _stage_env_for sets the env var per spawn
env[NOVA_BEARER_TOKEN_ENV] = self._resolve_nova_bearer()  # = get_fresh_nova_token() or ""
```

The `:-` default is load-bearing: without it Claude Code refuses to parse the config when the var is unset (which would crash the loader if Nova wasn't connected). The empty-string default makes the header expand to `Bearer ` — server returns 401 at call time, which is recoverable.

**General principle:** prefer `${VAR:-}` for any short-lived bearer if the consuming process can set the env var per spawn. Keep `headersHelper` for cases where the token source is genuinely a separate process you don't control.

## Trap 3: Better-Auth rotates refresh_tokens — concurrent ECS tasks burn each other

commcare.app uses Better-Auth, which **rotates the refresh_token on every successful refresh**. With 2+ ace-web tasks behind the ALB, a real concurrency bug emerges:

1. Task A and Task B both read the blob with refresh_token `R1`.
2. Both POST `/token` with `R1`.
3. AS accepts the first request → returns `(access_token A2, refresh_token R2)`. Task A persists the rotated blob.
4. AS rejects the second with `400 invalid_grant: "session not found"` because `R1` is now consumed.
5. Task B's `_refresh()` returns None → `NOVA_BEARER_TOKEN=""` → that user's chat 401s on Nova.

Discovered by manually probing refresh during prod verification — burning the stored refresh_token left ace-web unable to refresh until I re-ran OAuth.

**Fix** (`_refresh_with_lock` in `apps/common/nova_auth_flow.py`): SETNX-based lock on `nova:refresh-lock` (TTL 30s). Holder refreshes; non-holders poll the DB at 200ms until the holder rotates the blob, then return its access_token without POSTing themselves. Lock release uses Lua compare-and-delete so a stuck holder whose TTL expires can't accidentally delete a newer holder's lock when it eventually wakes up.

Redis-down degrades to lockless refresh (logged WARNING) — strictly worse for multi-task deploys, but better than no Nova at all for single-task / dev.

This pattern generalizes: **any OAuth provider that rotates refresh_tokens needs cross-process refresh serialization for any deploy with >1 worker.** Don't replicate this trap for the next provider.

## Trap 4: The bot identity needs the `_can_write_global` perm path

OAuth views were initially gated on `request.user.is_staff` — but the canonical automation account `ace@dimagi-ai.com` (per CLAUDE.md) intentionally isn't staff. Without alignment, a script using `/auth/e2e-login/` to drive Nova OAuth as the bot would 302 to `/auth/login/`.

The Claude credentials path already had this exact pattern: `apps.common.auth_views._can_write_global(user)` — `is_staff OR email.endswith("@dimagi-ai.com")`. PR #180 aligned the Nova views to use the same helper.

**For any future credential-management view that the bot needs to drive: import `_can_write_global` and use it. Don't gate on `is_staff` alone.**

## Trap 5: Single shared identity per instance

Nova auth here is **one global blob** (`SystemConfig['nova_credentials_blob']`) under one Google identity (`ace@dimagi-ai.com`). All workspaces / users share it. Decision driven by:

- The HQ API key Nova uses for app uploads is per-Google-account; we want all builds to land in the same place.
- Per-user OAuth would require per-user consent + per-user token storage + significant per-user UI. Out of scope.
- Audit attribution lives in ace-web logs (which user triggered which chat), not in Nova's UI (everything shows up as the bot).

Do not generalize this to per-user without first revisiting the HQ-API-key story.

## Recovery / smoke test

When the stored blob gets into a bad state (refresh-token burned, session revoked, etc.):

1. `POST /api/auth/nova/disconnect` (admin or bot) — clears `SystemConfig['nova_credentials_blob']`.
2. Visit `/auth/nova/initiate/` in a browser as a `_can_write_global` user → Google sign-in (as `ace@dimagi-ai.com`) → Allow → callback writes a fresh blob.
3. `GET /api/auth/nova/status` should report `connected: true, valid: true, scope: "openid profile email offline_access nova.read nova.write nova.hq.read nova.hq.write"`.
4. End-to-end smoke: open a chat, ask the model to call `mcp__plugin_nova_nova__list_apps(limit=3)`. Result should be the integer count of apps in your Nova workspace.

The Settings page (`/settings`) has the same Connect / Reconnect / Disconnect controls behind the `Nova MCP` panel.

## Key files

| File | Role |
|------|------|
| `apps/common/nova_auth_flow.py` | Blob storage, refresh, validate, refresh-lock |
| `apps/auth/nova_oauth_views.py` | `/auth/nova/initiate/` + `/auth/nova/callback/` (HTML/redirect) |
| `apps/common/auth_views.py` | `/api/auth/nova/{status,disconnect}` (JSON), `_can_write_global` helper |
| `apps/common/cli_backend.py` | `_stage_env_for` injects `NOVA_BEARER_TOKEN` into the spawn env |
| `Dockerfile` | Rewrites `/app/vendor/nova-plugin/.mcp.json` to use `${NOVA_BEARER_TOKEN:-}` expansion |
| `frontend/src/pages/SettingsPage.tsx` | Nova MCP panel (status, Connect/Reconnect/Disconnect) |
