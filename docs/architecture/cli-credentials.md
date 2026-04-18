# CLI credential handoff — architecture

**TL;DR:** the claude CLI already knows how to auth, refresh, and use its
own credentials. We don't reinvent any of that. A developer runs a
script on their laptop that ships the CLI's own credential blob to the
server, which writes it to the path the CLI reads from. That's it.

## Three components

```
┌──────────────────────┐      ┌──────────────────────┐      ┌──────────────────────┐
│ Developer laptop     │      │ ace-web server       │      │ claude -p subprocess │
│ (macOS / Linux)      │      │ (ECS Fargate)        │      │ (inside the server)  │
├──────────────────────┤      ├──────────────────────┤      ├──────────────────────┤
│ ~/.claude/           │      │ SystemConfig table   │      │ $HOME=/app/.ace-     │
│   .credentials.json  │ ───▶ │   claude_credentials │ ───▶ │   claude-home        │
│ OR macOS Keychain    │      │   _blob (JSON)       │      │                      │
│ "Claude Code-        │      │                      │      │ reads                │
│  credentials"        │      │ $ACE_CLAUDE_HOME/    │      │   $HOME/.claude/     │
│                      │      │   .claude/           │      │   .credentials.json  │
│                      │      │   .credentials.json  │      │                      │
│                      │      │   (same JSON)        │      │ refreshes via        │
│                      │      │                      │      │   refreshToken       │
└──────────────────────┘      └──────────────────────┘      └──────────────────────┘
        ↑                              ↑                              ↑
 scripts/ace_cli_login.py     POST /api/auth/cli/upload      auth_flow._write_
 reads it                     writes both sides              credentials_file()
```

## Data flow

### Upload (one-time, or on rotation)

1. Dev runs `claude setup-token` once on their laptop, or just uses
   `claude -p` normally — the CLI caches its credentials in
   `~/.claude/.credentials.json` (Linux) or the macOS Keychain under
   service `Claude Code-credentials`.
2. `scripts/ace_cli_login.py` reads that blob (platform auto-detect:
   `security find-generic-password` on macOS, file read on Linux).
3. POSTs the full blob — `{"claudeAiOauth": {accessToken, refreshToken,
   expiresAt, scopes, ...}}` — to `POST /api/auth/cli/upload`, authed
   with a personal bearer token minted at `/settings`.
4. `apps/common/auth_views.cli_auth_upload` calls
   `auth_flow.store_credentials_blob(blob)`.

### Persistence (three places, same data, different purposes)

- `SystemConfig[claude_credentials_blob]` — canonical durable store,
  survives container restarts.
- `SystemConfig[claude_oauth_token]` — extracted `accessToken` for the
  legacy env-var path (kept for backward compat).
- `$ACE_CLAUDE_HOME/.claude/.credentials.json` — ephemeral file that
  claude CLI reads **and writes back to** when it refreshes. Lost on
  container restart, but the next boot rewrites it from DB and the CLI
  refreshes again if needed.
- `os.environ["CLAUDE_CODE_OAUTH_TOKEN"]` — hot cache for the
  `claude -p` subprocess env.

### Boot

`auth_flow.load_stored_token()` reads the blob from DB, writes the
credentials file, sets the env var. Lazy — runs on first call to
`get_stored_token()`, not in `AppConfig.ready()`.

### Chat turn

`apps/common/cli_backend.CLIBackend._build_env` sets
`HOME=ACE_CLAUDE_HOME`, spawns `claude -p --output-format stream-json`.
The CLI finds `.credentials.json` at `$HOME/.claude/.credentials.json`,
uses the accessToken, refreshes via refreshToken if expired, streams
structured JSON events back to our consumer. **No PTY, no regex, no
parsing.**

## The HOME invariant

Everything hinges on one rule: every process that touches claude CLI
state runs with `HOME=ACE_CLAUDE_HOME`. If any process runs with the
container's default HOME (`/home/app`), it reads/writes a different
credentials file and the handoff silently breaks.

Enforced in:
- `apps/common/cli_backend.py` — `_build_env` sets HOME for `claude -p`.
- `apps/common/auth_flow.py` — `_write_credentials_file` writes to
  `$ACE_CLAUDE_HOME/.claude/.credentials.json`.
- `apps/common/auth_flow.py` — `_check_token_via_cli` (live validation)
  also sets HOME.

## Validation

`GET /api/auth/cli/status` calls `auth_flow.validate_stored_token()`,
which runs `claude -p "ok"` and looks for `"subtype":"success"` in the
stream-json output. Same function is exposed as
`auth_flow.cli_is_ready` and used by
`apps/common/backend_selector.get_chat_backend()`, so the status banner
and the actual chat backend selection always agree. Result is cached
for 5 minutes; `store_credentials_blob` invalidates the cache.

## Rotation model

| Event | Who handles it | What happens |
|-------|----------------|--------------|
| Access token expires (hours/days) | claude CLI itself | CLI refreshes in-place via refreshToken, writes updated blob to the credentials file. DB is stale but harmless because the CLI doesn't mid-process re-read the file. |
| Container restart | `load_stored_token()` | Re-seeds the credentials file from DB. If access token has expired, CLI refreshes again on next use. |
| Refresh token expires (weeks/months) | Dev | Re-run `ace_cli_login.py` from laptop. New blob overwrites DB + file. |
| Anthropic revokes everything | Dev | Same: re-auth locally, re-upload. |

## Fallback

If no credential blob is present (fresh container, no upload yet),
`apps/common/backend_selector.get_chat_backend()` falls back to
`ApiBackend` — direct Anthropic API via `ANTHROPIC_API_KEY` from
Secrets Manager. Chat keeps working, metered against the API key
instead of the subscription. The `/auth/cli` banner correctly shows
"not connected" so the dev knows to upload.

## Key files

| File | Role |
|------|------|
| `scripts/ace_cli_login.py` | Laptop-side reader + uploader |
| `apps/common/auth_flow.py` | `store_credentials_blob`, `load_stored_token`, `validate_stored_token` |
| `apps/common/auth_views.py` | `cli_auth_upload`, `cli_auth_status` |
| `apps/common/backend_selector.py` | Picks CLIBackend vs ApiBackend based on `cli_is_ready()` |
| `apps/common/cli_backend.py` | Runs `claude -p` with `HOME=ACE_CLAUDE_HOME` |
| `config/settings/base.py` | `ACE_CLAUDE_HOME` setting — the linchpin |
| `frontend/src/pages/AuthCliPage.tsx` | Status + upload instructions |

## What we deleted (and why)

Before this design, the server ran `claude setup-token` itself via a
PTY, parsed the terminal output to extract the OAuth token, and stored
the token as a string. One week of debugging showed the approach was
fundamentally fragile:

- PTY line wrap depended on terminal width set by the CLI
- ANSI cursor positioning escapes embedded inside token output got
  eaten by the ANSI stripper along with adjacent token chars
- The "Store this token securely..." line after the token got
  concatenated into the token by greedy regex after newline removal
- Linux `claude setup-token` doesn't write a credentials file — only
  prints to stdout — so there was no non-PTY path to the token

Deleted code: `_AuthSession`, `start`/`complete`/`poll`/`cancel`
functions, `_extract_url`, `_extract_token`, all ANSI escape handling,
and four REST endpoints. ~600 lines gone. Replaced by
`store_credentials_blob` + `cli_auth_upload` + the laptop-side script.
