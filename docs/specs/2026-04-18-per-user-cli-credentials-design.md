# Per-user CLI credentials — Design

**Date:** 2026-04-18
**Status:** Approved for execution.
**Parent spec:** `docs/specs/2026-04-08-ace-web-design.md` (§ auth/chat-backend).
**Related:** Phase 4 ingest + personal bearer tokens (`docs/specs/2026-04-09-phase-4-library-ingest-design.md`); CLI credential upload architecture (`docs/architecture/cli-credentials.md`).

---

## 1. Goal

Each ace-web user can upload their own Claude CLI credential blob so that web-originated chat runs on **their** Max subscription, not a shared admin token. The existing global `SystemConfig` blob stays as a fallback (and as the bootstrap for users who haven't uploaded yet).

Out of scope: per-turn hook-based session mirroring, bidirectional web↔CLI continuation, Claude Desktop integration. Those remain the domain of the already-shipped Phase 4 `ace-upload` flow.

## 2. Decisions

| Decision | Resolution | Rationale |
|---|---|---|
| Token selection at chat time | Session owner's blob, forever. | Simplest semantics; matches user expectation ("I started it, it burns my quota"). Multi-player participants send on the owner's token. |
| Fallback when owner has no blob | Use the global `SystemConfig` blob. | Keeps first-time / guest chat working without forcing upload before first use. |
| Fallback when owner's blob is invalid | Also fall back to global. Log a warning; surface a banner on the Settings page. | Avoids hard-breaking a session mid-conversation. User can fix the token at their leisure. |
| Encryption at rest | Encrypt both per-user and global blobs (Fernet via `django-cryptography` or equivalent). Same migration that introduces per-user storage migrates the global row into the encrypted column. | OAuth tokens with refresh are sensitive; adding per-user surface area justifies the lift. Transparent to the rest of the app — `get_stored_token()` is the only reader. |
| Admin "promote to global" | Separate button on Settings (admin-only). Copies the admin's current user blob into the `SystemConfig` global row. Both rows stay; promoting updates global in place. | Clear mental model: the admin has a personal blob like anyone else, plus a distinct lever for "make this the fallback." |
| Session-blob pinning | No. Sessions always resolve the owner's current blob at send time. | Simpler than snapshotting. If owner rotates their token, old sessions start using the new one seamlessly. |
| Existing sessions in flight | Silently start using owner's personal blob as soon as they upload one. | Per above. No explicit migration — the resolve-at-send-time rule gets it for free. |
| `ace-upload --watch` mode | Included, low priority. Debounced polling (default 60s) of `~/.claude/projects/`, uploads any JSONL whose mtime has been stable for ≥ 2 polls. | Hands-off batch mirror without the per-turn chattiness we explicitly rejected. Purely additive to Phase 4's manual flow. |
| Settings page | Shows per-user token status (Active / Expired / Not uploaded) + "Upload from this browser via skill" instructions. Admin sees a second section for the global fallback. | Makes the two concepts visible rather than hiding one behind the other. |

## 3. Data model

### 3.1 New table

`apps/common/models.py` — add `UserCredential`:

```python
class UserCredential(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cli_credential",
    )
    blob_encrypted = EncryptedTextField()   # JSON-serialized claudeAiOauth blob
    token_prefix = models.CharField(max_length=20)   # sk-ant-oat01-xx (for display)
    uploaded_at = models.DateTimeField(auto_now=True)
    last_validated_at = models.DateTimeField(null=True, blank=True)
    last_validation_ok = models.BooleanField(null=True)

    class Meta:
        db_table = "user_credentials"
```

One row per user. `blob_encrypted` holds the full `{"claudeAiOauth": {...}}` JSON. `token_prefix` is the first 15 chars of the access token, shown in the Settings UI (no full token ever re-exposed).

### 3.2 Global row reshape

Existing `SystemConfig[claude_credentials_blob]` row — same key, same semantics, but the `value` column moves behind the same encryption. Migration re-writes the row in place.

Existing `SystemConfig[claude_oauth_token]` legacy row (access-token-only) — drop. Current code already prefers the blob; the migration should verify the blob row exists, then delete the legacy row.

### 3.3 Resolver

`apps/common/auth_flow.py::get_stored_token()` becomes user-aware. Current signature:

```python
def get_stored_token() -> str | None:
    return os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or load_stored_token()
```

New signature:

```python
def get_stored_token(user: User | None = None) -> tuple[str, str] | None:
    """Return (access_token, source) where source in {"user", "global", "env"}."""
```

Resolution order:
1. If `user` has a `UserCredential` and its blob's access token is real → `("...", "user")`.
2. Global `SystemConfig` blob → `("...", "global")`.
3. `CLAUDE_CODE_OAUTH_TOKEN` env var (dev / test fallback) → `("...", "env")`.
4. `None`.

The existing `validate_stored_token()` gains an optional `user=` kwarg and runs the live CLI check against whichever blob the resolver picked.

## 4. Chat path wiring

`apps/common/backend_selector.py` + `apps/sessions/consumers.py` — the thread that spawns `claude -p` needs the session owner's blob:

1. When a WebSocket message arrives for `session=<slug>`, look up `session.owner`.
2. Call `get_stored_token(user=session.owner)`.
3. Write that blob to the subprocess's `$CLAUDE_CODE_OAUTH_TOKEN` + `.credentials.json` path *for that subprocess only* (not to the shared `ACE_CLAUDE_HOME`, which stays pointing at the global blob for other consumers).
4. Spawn the subprocess with a per-session `HOME` override.

Concretely: each `CLIBackend` invocation gets a short-lived temp dir at `/tmp/ace-cli/<session-slug>-<uuid4>/` seeded with the resolved blob, torn down at end of turn. Per-invocation UUID handles the near-simultaneous-sends case in multi-player sessions where two messages might overlap. This keeps per-user blobs isolated — no chance of one user's `claude -p` accidentally reading another user's credentials file, and no churn on the shared `ACE_CLAUDE_HOME`, which continues to hold the global blob for the one-shot validation probe in `_check_token_via_cli`.

The validation cache in `auth_flow.py` grows a per-user key (`(user_id, token)` instead of just `token`) so personal and global validation results don't collide.

## 5. Credential upload flow

### 5.1 Endpoint change

`POST /api/auth/cli/upload` (`apps/common/auth_views.py`) today writes to the single global row. Updated behavior:

- **Default:** write to `request.user`'s `UserCredential` row. Create or update.
- **`?scope=global` query param, admin-only:** write to the global `SystemConfig` blob (the existing behavior). Rejected with 403 if `request.user.is_staff` is false.
- Response shape unchanged: `{data: {stored, authenticated, token_prefix, scope}}` where `scope` is `"user"` or `"global"`.

Live validation runs against the blob that was just written.

### 5.2 Status endpoint

`GET /api/auth/cli/status` returns both pieces of state so the UI can render them independently:

```json
{
  "data": {
    "authenticated": true,
    "user": {"has_blob": true, "token_prefix": "sk-ant-oat01-wk", "validated_at": "...", "valid": true},
    "global": {"has_blob": true, "token_prefix": "sk-ant-oat01-xy", "valid": true, "is_admin_only_field": true}
  },
  "error": null
}
```

Non-admin users still see `global.has_blob` + `global.valid` (so they know the fallback works) but cannot see the admin-scoped details.

### 5.3 Settings page

`/settings` gains a "Claude CLI credentials" section:

- **Your token** panel — Active / Expired / Not uploaded badge + token prefix + "upload from this browser" instructions pointing at `/ace-web:create-cli-credentials`.
- **Instance fallback** panel (admin only) — token prefix, validity badge, "promote my token to fallback" button.

### 5.4 Skill update

`.claude/skills/ace-web/create-cli-credentials/SKILL.md` + `scripts/ace_cli_login.py`:

- Default scope = `user`.
- `--global` flag on `ace_cli_login.py` (gated by admin-only endpoint; fails gracefully for non-admins).
- Skill doc gets a new "scope" preamble clarifying personal vs global.

## 6. `ace-upload --watch` (optional addition)

Lives in `apps/ingest/cli.py` next to the existing upload entrypoint. Behavior:

- `ace-upload --watch [--root ~/.claude/projects] [--interval 60]`
- Every `interval` seconds, walk `root` for `*.jsonl` files.
- For each file: track `(path, size, mtime, sha1)` in a small SQLite state file at `~/.ace/watch-state.sqlite`.
- If mtime changed since last check but stabilizes across two consecutive polls, upload via the existing ingest endpoint. This is the debounce.
- On 409 (duplicate `cli_session_id`), silently skip — that session is already mirrored.
- On token failure, exit with a clear message pointing at the skill.

Keep it dumb. No retry, no compression, no parallelism. Users who want it run it in a `tmux`/`launchd` shell; we don't ship an installer for it in this spec.

## 7. Security

### 7.1 Encryption

`django-cryptography`'s `EncryptedTextField`. Prod **must** set a dedicated `ACE_FIELD_ENCRYPTION_KEY` (AWS Secrets Manager); dev/CI falls back to `settings.SECRET_KEY` for ergonomics. Startup check refuses to boot in `DEBUG=False` if the dedicated key is missing. Key rotation is supported by the library but out of scope for this spec (runbook to be written on first rotation).

### 7.2 Logging

`auth_flow.py` already logs prefix-only (`token[:15]`). Audit all call sites to ensure no accidental full-token logging. Add a unit test that scans structured log output for sequences longer than the prefix.

### 7.3 Access control

- A user can only read / write their own `UserCredential`.
- Only staff can read or mutate the global `SystemConfig` blob via the API.
- The Django admin gets a read-only `UserCredential` admin (showing prefix + timestamps, never the encrypted blob).

### 7.4 Threat reduction

Encrypted-at-rest blobs mean a DB read compromise no longer hands the attacker live Claude tokens. They'd need the field-encryption key too, which lives in AWS Secrets Manager alongside the other sensitive env vars. This is the main security win of the spec.

## 8. Testing

Backend (`pytest`):

- `apps/common/tests/test_auth_flow_resolver.py` — resolver returns user blob when present, global otherwise, env when both missing.
- `apps/common/tests/test_auth_views_scope.py` — upload default scope = user; `?scope=global` as non-admin → 403; as admin → writes global row.
- `apps/common/tests/test_user_credential_encryption.py` — plaintext blob in, ciphertext at rest, same bytes on read.
- `apps/common/tests/test_chat_token_selection.py` — chat message on `session_owned_by(user_a)` picks user_a's blob; on a session whose owner has no blob, picks global.
- Per-session `HOME` isolation — integration test that two concurrent chat sessions for different owners don't see each other's `.credentials.json`.
- Cache isolation — `validate_stored_token(user=a)` and `(user=b)` don't pollute each other's cache.

Frontend (manual walkthrough — Phase 4 precedent):

- Settings page shows correct state for: non-admin with no blob, non-admin with valid blob, admin with both blobs, admin after promoting.
- Chat initiated by a user with their own blob → request reaches Anthropic as that user's token (verified via access token prefix in server logs).

Migration:

- Forward migration re-encrypts the existing global blob; running `validate_stored_token()` after migrate still returns true against labs data.

## 9. Rollout

1. Migration lands + ships in a single deploy — same image adds the `UserCredential` table, re-encrypts the existing global `SystemConfig` blob, and cuts the resolver over to the new columns. No two-phase deploy: for one global row, a single transactional migration is safer than dual-column straddling. Rollback is "revert image + restore DB snapshot." No behavior change visible to users (everyone still uses global until they upload).
2. Settings page ships with per-user upload surface enabled but optional.
3. Chat path cutover — resolver starts preferring per-user. Silent fallback to global if the user hasn't uploaded.
4. Notify team: "your own Max subscription now powers your ace-web chat; visit Settings to upload."
5. Monitor logs for `token_source=global` after cutover. If it stays > 0 past a grace period, that's teammates who haven't uploaded; nudge them individually.
6. `ace-upload --watch` ships separately; no dependency on the auth changes.

## 10. New & modified files

```
apps/
├── common/
│   ├── models.py                      # MODIFIED: UserCredential
│   ├── auth_flow.py                   # MODIFIED: user-aware resolver + per-user cache
│   ├── auth_views.py                  # MODIFIED: scope param, admin-gated global writes
│   ├── backend_selector.py            # MODIFIED: per-subprocess HOME + blob staging
│   ├── migrations/
│   │   └── NNNN_user_credentials.py   # NEW: table + re-encrypt global row
│   └── tests/
│       ├── test_auth_flow_resolver.py  # NEW
│       ├── test_auth_views_scope.py    # NEW
│       ├── test_user_credential_encryption.py  # NEW
│       └── test_chat_token_selection.py  # NEW
├── sessions/
│   └── consumers.py                   # MODIFIED: thread through session.owner to resolver
└── ingest/
    └── cli.py                         # MODIFIED: add --watch mode
frontend/src/
├── pages/SettingsPage.tsx             # MODIFIED: two-panel credentials section
└── api/auth.ts                        # MODIFIED: new status shape
scripts/
└── ace_cli_login.py                   # MODIFIED: default scope=user, --global flag
.claude/skills/ace-web/create-cli-credentials/
└── SKILL.md                           # MODIFIED: scope guidance
deploy/aws/task-definition.json        # MODIFIED: ACE_FIELD_ENCRYPTION_KEY via Secrets Manager
pyproject.toml                         # MODIFIED: add django-cryptography
```

## 11. Explicitly deferred

- Hook-based per-turn session mirroring.
- Writing back to local CLI JSONL files from the web.
- Claude Desktop integration (no hook surface exists).
- Agent SDK wrapper launcher.
- Multi-blob-per-user (e.g., separate tokens for separate Anthropic orgs). One blob per user is sufficient.
- Key rotation procedure for `ACE_FIELD_ENCRYPTION_KEY` (library supports it; runbook to be written when first needed).
- Rate limiting / quota visibility — surfacing Anthropic's per-token rate state to the user in-app.
- "Bring your own API key" as an alternative to Max subscription blobs.

## 12. References

- Current credential flow: `docs/architecture/cli-credentials.md`
- Personal bearer tokens (for upload auth): `docs/specs/2026-04-09-phase-4-library-ingest-design.md` § 5.1
- `auth_flow.py` today: `apps/common/auth_flow.py`
- Upload endpoint today: `apps/common/auth_views.py`
- Skill: `.claude/skills/ace-web/create-cli-credentials/SKILL.md`
