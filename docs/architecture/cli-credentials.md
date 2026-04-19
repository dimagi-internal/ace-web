# CLI credential handoff — architecture

**TL;DR:** the claude CLI already knows how to auth, refresh, and use its
own credentials. We don't reinvent any of that. A developer runs a
script on their laptop that ships the CLI's own credential blob to the
server, which writes it to the path the CLI reads from. That's it.

## Per-user credentials (2026-04-19)

The model has two tiers. Each ace-web user can upload their own
credential blob via `POST /api/auth/cli/upload` (default `scope=user`);
chat then runs on **that user's** Max subscription. The original
`SystemConfig` global blob is retained as a fallback so first-time and
guest users still get working chat without needing to upload first.
Admins (`is_staff`) can still write the global row by passing
`?scope=global`, or copy their personal blob into global via the
`POST /api/auth/cli/promote` endpoint.

See `docs/specs/2026-04-18-per-user-cli-credentials-design.md` for the
full design (decision matrix, encryption choice, fallback rules,
multi-player semantics).

The resolver `auth_flow.get_stored_token(user=...)` returns
`(token, source)` where `source` is `"user"`, `"global"`, or `"env"`,
in that order. Both `validate_stored_token(user=...)` and
`get_chat_backend(user=...)` take the same user, so the
`/api/auth/cli/status` "Active" banner and the actual send path can
never disagree.

## Three components

```
┌──────────────────────┐      ┌──────────────────────┐      ┌──────────────────────┐
│ Developer laptop     │      │ ace-web server       │      │ claude -p subprocess │
│ (macOS / Linux)      │      │ (ECS Fargate)        │      │ (per chat invocation)│
├──────────────────────┤      ├──────────────────────┤      ├──────────────────────┤
│ ~/.claude/           │      │ UserCredential       │      │ $HOME=/tmp/ace-cli/  │
│   .credentials.json  │ ───▶ │   (per-user blob,    │ ───▶ │   <slug>-<uuid>      │
│ OR macOS Keychain    │      │    encrypted)        │      │                      │
│ "Claude Code-        │      │                      │      │ reads                │
│  credentials"        │      │ SystemConfig         │      │   $HOME/.claude/     │
│                      │      │   claude_credentials │      │   .credentials.json  │
│                      │      │   _blob (fallback)   │      │                      │
│                      │      │                      │      │ refreshes via        │
│                      │      │                      │      │   refreshToken;      │
│                      │      │                      │      │ refreshed blob is    │
│                      │      │                      │      │ persisted back to    │
│                      │      │                      │      │ DB before teardown   │
└──────────────────────┘      └──────────────────────┘      └──────────────────────┘
        ↑                              ↑                              ↑
 scripts/ace_cli_login.py     POST /api/auth/cli/upload      CLIBackend._stage_env_for
 reads it                     writes per-user OR global      + _persist_refreshed_blob
```

## Data flow

### Upload (one-time, or on rotation)

1. Dev runs `claude setup-token` once on their laptop, or just uses
   `claude -p` normally — the CLI caches its credentials in
   `~/.claude/.credentials.json` (Linux) or the macOS Keychain under
   service `Claude Code-credentials`.
2. `scripts/ace_cli_login.py` (or `/ace-web:create-cli-credentials`) reads
   that blob (platform auto-detect: `security find-generic-password` on
   macOS, file read on Linux).
3. POSTs the full blob — `{"claudeAiOauth": {accessToken, refreshToken,
   expiresAt, scopes, ...}}` — to `POST /api/auth/cli/upload`, authed
   with a personal bearer token minted at `/settings`.
4. `apps/common/auth_views.cli_auth_upload`:
   - default `scope=user` → `auth_flow.store_user_credentials_blob(user, blob)`
     writes `UserCredential` for the calling user.
   - `?scope=global` (admin only) → `auth_flow.store_credentials_blob(blob)`
     writes the shared `SystemConfig` row.
   Both paths run a live validation probe (`validate_stored_token`) before
   returning so the response surfaces whether the freshly-uploaded blob
   actually works.

### Persistence

- `UserCredential.blob_encrypted` — per-user durable store, encrypted at
  rest via `django-cryptography`. One row per user.
- `SystemConfig[claude_credentials_blob]` — global fallback durable store.
- `SystemConfig[claude_oauth_token]` — legacy extracted access token, kept
  for back-compat with deploys that predate the blob migration.
- Per-invocation staged HOME under `/tmp/ace-cli/<slug>-<uuid>/.claude/.credentials.json` — what each `claude -p`
  subprocess actually reads from. Created at the start of each chat,
  read back by `_persist_refreshed_blob`, then `rmtree`'d.
- `os.environ["CLAUDE_CODE_OAUTH_TOKEN"]` — best-effort hot cache for
  the subprocess env.

### Boot

`auth_flow.load_stored_token()` reads the global blob from DB, writes the
shared `ACE_CLAUDE_HOME` credentials file, sets the env var. Lazy — runs
on first call to `get_stored_token()`, not in `AppConfig.ready()`. This
covers the no-user / startup-check path; per-user blobs are loaded
lazily by `get_stored_token(user=...)`.

### Chat turn

`apps/common/cli_backend.CLIBackend._stage_env_for(session)` resolves
the session owner's blob via `get_stored_token(user=session.owner)`,
writes it to `/tmp/ace-cli/<slug>-<uuid>/.claude/.credentials.json`,
sets `HOME` for THIS subprocess only, and returns
`(env, staged_home, source)`. The CLI finds `.credentials.json` at
`$HOME/.claude/.credentials.json`, uses the accessToken, refreshes via
refreshToken if expired, streams structured JSON events back to our
consumer. **No PTY, no regex, no parsing.**

When the subprocess exits, **before** the staged HOME is removed,
`_persist_refreshed_blob(session, source, staged_home)` reads the
(possibly-refreshed) credentials file back and writes the new blob to
the storage layer it came from (`UserCredential` for `source="user"`,
`SystemConfig` for `source="global"`, no-op for `source="env"`). This
preserves the CLI's native OAuth refresh: without it, Anthropic's
single-use refresh tokens would be burned by one chat and the next chat
would 401.

## Per-invocation HOME isolation

Two concurrent chats from different users must NOT clobber each other's
`~/.claude/.credentials.json`. Every chat invocation gets its own
`/tmp/ace-cli/<slug>-<uuid>/` HOME directory, used for ONE subprocess
and torn down (after refresh persistence) in the outer `finally`.

Enforced in:
- `apps/common/cli_backend.py` — `_stage_env_for` builds the temp HOME
  with the resolved owner's blob; `_persist_refreshed_blob` writes any
  refresh back; `_teardown_staged_home` rmtrees the dir.
- `apps/common/auth_flow.py` — `_check_token_via_cli(blob_json=..., on_refresh=...)`
  does the same for the validation probe path. The `on_refresh`
  callback (built by `_build_refresh_persister`) is invoked just before
  the staged HOME is removed.

## Validation

`GET /api/auth/cli/status` calls
`auth_flow.validate_stored_token(user=request.user)`, which runs
`claude -p "ok"` in a per-invocation staged HOME and looks for
`"subtype":"success"` in the stream-json output. The same function is
exposed as `auth_flow.cli_is_ready` and used by
`apps/common/backend_selector.get_chat_backend(user=...)`, so the
status banner and the actual chat backend selection always agree for
THIS user. Result is cached for 5 minutes (keyed on `(token, source)`
so per-user results don't collide with global);
`store_credentials_blob` invalidates the cache.

## Rotation model

| Event | Who handles it | What happens |
|-------|----------------|--------------|
| Access token expires (hours/days) | claude CLI itself | CLI refreshes in-place via refreshToken, writes updated blob to the staged credentials file. `_persist_refreshed_blob` writes it back to `UserCredential` (or global `SystemConfig`) before teardown so the next chat has the fresh refresh token. |
| Container restart | `load_stored_token()` for global; `get_stored_token(user=...)` for per-user (lazy on first request) | Re-seeds whichever staged credentials file is needed from DB. If access token has expired, CLI refreshes again on next use. |
| Refresh token expires (weeks/months) | Dev | Re-run `ace_cli_login.py` (or `/ace-web:create-cli-credentials`) from laptop. New blob overwrites `UserCredential` (default) or `SystemConfig` (admin scope=global). |
| Anthropic revokes everything | Dev | Same: re-auth locally, re-upload. |

## Fallback chain

When chat starts:
1. `get_chat_backend(user=session.owner)` calls `cli_is_ready(user=...)`.
2. `cli_is_ready` resolves `(token, source)` via `get_stored_token`:
   the user's `UserCredential` first, then the global `SystemConfig`
   blob, then `CLAUDE_CODE_OAUTH_TOKEN` env var.
3. If a per-user blob exists but `last_validation_ok=False`, the
   resolver skips it and falls through to global. The user sees
   "Uploaded but failing" in the Settings UI and can re-upload.
4. If nothing resolves and `ANTHROPIC_API_KEY` is set, fall back to
   `ApiBackend` — direct Anthropic API, metered against the API key
   instead of the subscription.
5. Otherwise return `CLIBackend` as a dead-end so the chat surfaces a
   clear "no CLI token" error.

## Key files

| File | Role |
|------|------|
| `scripts/ace_cli_login.py` | Laptop-side reader + uploader |
| `.claude/skills/create-cli-credentials/` | Same flow as a Claude Code skill (`/ace-web:create-cli-credentials`) |
| `apps/common/models.py` | `UserCredential`, `SystemConfig` |
| `apps/common/auth_flow.py` | `store_credentials_blob`, `store_user_credentials_blob`, `get_stored_token`, `validate_stored_token`, `_check_token_via_cli`, `_build_refresh_persister` |
| `apps/common/auth_views.py` | `cli_auth_upload`, `cli_auth_status`, `cli_auth_promote` |
| `apps/common/backend_selector.py` | Picks CLIBackend vs ApiBackend based on `cli_is_ready(user=...)` |
| `apps/common/cli_backend.py` | Runs `claude -p` in a per-invocation staged HOME; `_stage_env_for` + `_persist_refreshed_blob` |
| `frontend/src/pages/SettingsPage.tsx` | Two-panel UI: personal vs global credential status |

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

The earlier "single global HOME invariant" model — where every process
ran with `HOME=ACE_CLAUDE_HOME` — was also retired in favor of
per-invocation staged HOMEs. That guarantee was correct for a single
shared blob but couldn't prevent two concurrent chats from different
users overwriting each other's credentials file mid-refresh.
