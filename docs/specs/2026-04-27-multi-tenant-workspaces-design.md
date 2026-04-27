# Multi-Tenant Workspaces — Design Spec

**Date:** 2026-04-27
**Status:** Draft — awaiting review.
**Scope:** Turn ace-web from a Dimagi-team-only single-tenant deployment
into a true multi-tenant product. Anyone with a CommCare Connect account
can sign in, create an ACE Workspace pointing at a Google Drive folder
they share with the platform's service account, invite teammates, and
"say go" without ever touching the CLI plugin.

## 1. Overview

Today ace-web has three tightly-coupled assumptions baked in:

1. **One Drive root for everyone.** `ACE_DRIVE_ROOT_FOLDER_ID` is a single
   environment variable pinned to the Dimagi team's shared folder
   (`config/settings/base.py:158`). Every authenticated user reads from
   the same root.
2. **Dimagi staff only.** The OAuth callback at
   `apps/auth/oauth_views.py:112` rejects any email that isn't `@dimagi.com`.
3. **No data scoping.** Once authenticated, every user can see every opp.
   There is no concept of "my team's opps."

These assumptions made sense for the Phase 1–4 internal-only product.
They are the load-bearing blockers for the next phase: third-party,
web-only users.

This spec replaces those three assumptions with a single new concept —
the **Workspace** — and the membership/role model around it. The CLI
plugin (`ace`) does not change. The internal Dimagi flow does not break.
The path "log in → create workspace → connect a Drive folder → invite
teammates → run ACE" becomes a real product flow.

## 2. Goals

1. **A new web-only user can self-onboard end-to-end.** Sign in with
   Connect, create a workspace, share a Drive folder with the SA, verify
   access, and create their first opp — all from the browser, with no
   prior knowledge of ACE internals.
2. **Existing Dimagi CLI usage is undisturbed.** The `ace` plugin
   continues to write to its configured Drive folder. Web users see those
   opps under whichever workspace owns that folder. Zero plugin changes.
3. **Data is isolated by workspace.** Users see only opps, sessions,
   uploads, and share tokens belonging to workspaces they're a member of.
4. **Sharing is a first-class action.** A workspace owner can invite a
   teammate by email, assign a role, and revoke. No Django-admin-only
   workflows for everyday team management.

## 3. Non-goals

- **Per-workspace service accounts.** All workspaces share the single
  `ace-drive` SA. Each workspace's onboarding tells the user which SA
  email to share their folder with. Future work could provision SAs
  per-workspace; the schema accommodates it but v1 does not.
- **Per-user Claude credentials.** The CLI subscription / SystemConfig
  blob remains shared in v1. Per-user CLI tokens stay on the future-work
  list (`docs/plans/2026-04-18-per-user-cli-credentials.md`).
- **Cross-workspace search or aggregation.** A user with membership in
  multiple workspaces switches between them via a workspace picker. No
  unified "all my opps everywhere" view.
- **SSO / IdP integration beyond CommCare Connect.** Auth still goes
  through the existing Connect OAuth path. We're only changing the
  post-callback gate.
- **Automated SA folder-share verification on Google's side.** We can
  detect "the SA can read this folder" by trying to list it; we do not
  introspect Google's permission graph.

## 4. Architecture

### 4.1 New app: `apps/workspaces/`

Adds three Postgres tables. Drive remains the source of truth for opp
*content* — the workspace tables only describe membership, naming, and
folder binding.

```python
class Workspace(models.Model):
    slug = models.CharField(primary_key=True, max_length=64)
    display_name = models.CharField(max_length=200)
    drive_root_folder_id = models.CharField(max_length=100, unique=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    settings = models.JSONField(default=dict)         # forward-compat for per-workspace prefs
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class WorkspaceMembership(models.Model):
    workspace = models.ForeignKey(Workspace, related_name="memberships")
    user = models.ForeignKey(User, related_name="workspace_memberships")
    role = models.CharField(choices=[("owner","Owner"),("editor","Editor"),("viewer","Viewer")])
    invited_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    joined_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = [("workspace", "user")]

class WorkspaceInvite(models.Model):
    workspace = models.ForeignKey(Workspace, related_name="invites")
    email = models.CharField(max_length=200)          # may be a not-yet-registered user
    role = models.CharField(choices=...)              # default "editor"
    token = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        indexes = [models.Index(fields=["email", "-created_at"])]
```

**Why `drive_root_folder_id` is unique across workspaces:** the CLI
plugin reaches the web app via folder identity. If two workspaces could
claim the same folder, a CLI run would be ambiguous. Enforcing
uniqueness at the schema level is the cleanest way to keep CLI ↔ web
binding deterministic (see § 4.5).

### 4.2 Existing model changes

`apps/opps/models.py — OppWorkspace` (the per-opp row):

- New `workspace = ForeignKey(Workspace, on_delete=CASCADE, related_name="opps")`
- `slug` becomes unique-per-workspace, not globally unique
  (`unique_together = [("workspace", "slug")]`, drop the global PK; introduce
  a synthetic id and keep slug indexed)

`apps/sessions/models.py — Session`:

- New `workspace = ForeignKey(Workspace, null=True, on_delete=SET_NULL, related_name="sessions")`
- Sessions tied to an opp inherit the opp's workspace at creation time
- "Free" chat sessions (not tied to an opp) can stay null; they're
  visible only to the creator regardless of workspace

`apps/sessions/models.py — ShareToken`:

- New `workspace` FK (mirrors the underlying session's workspace)
- Public view at `/share/<token>/` continues to bypass auth, but the
  preview header now includes the workspace name for context

`apps/ingest/models.py — IngestUpload`:

- New `workspace` FK, set from the request user's "current workspace"
  at upload time (or from the URL when uploading via
  `/ace:run --ace-web-url`)

### 4.3 API surface

New endpoints, all under `/api/workspaces/`. All return the standard
`{data, error}` envelope (`apps/common/envelope`).

| Method  | Path                                 | Who          | Purpose                                                  |
|---------|--------------------------------------|--------------|----------------------------------------------------------|
| GET     | `/api/workspaces/`                   | any auth     | Workspaces I'm a member of                               |
| POST    | `/api/workspaces/`                   | any auth     | Create (display_name + drive_root_folder_id)             |
| GET     | `/api/workspaces/<slug>/`            | member       | Detail (members, my role, settings)                      |
| PATCH   | `/api/workspaces/<slug>/`            | owner        | Rename, edit settings                                    |
| DELETE  | `/api/workspaces/<slug>/`            | owner        | Detach (does NOT touch the Drive folder)                 |
| POST    | `/api/workspaces/<slug>/verify-drive-access/` | member | SA can list this folder? Returns sample files or error   |
| GET     | `/api/workspaces/<slug>/members/`    | member       | List members + roles                                     |
| POST    | `/api/workspaces/<slug>/members/`    | owner        | Invite by email + role → creates WorkspaceInvite         |
| PATCH   | `/api/workspaces/<slug>/members/<id>/`        | owner | Change role                                              |
| DELETE  | `/api/workspaces/<slug>/members/<id>/`        | owner | Remove member                                            |
| GET     | `/api/workspaces/drive-config/`      | any auth     | Returns `{service_account_email}` so UI shows it         |
| GET     | `/api/invites/<token>/`              | unauth ok    | Preview an invite (workspace name, role, inviter)        |
| POST    | `/api/invites/<token>/accept/`       | auth         | Accept (creates membership)                              |

**Existing opp endpoints scope to workspace membership.** Today
`apps/opps/views.py` reads `_resolve_ace_root_folder_id` from settings.
After this spec, the `_require_drive` helper resolves the workspace from
the URL (`/api/workspaces/<slug>/opps/...`) or from a header
(`X-ACE-Workspace`), checks membership, and uses that workspace's
`drive_root_folder_id` as the listing root. Cross-workspace requests
return 404 (not 403 — don't leak existence).

### 4.4 Auth: drop the @dimagi filter

`apps/auth/oauth_views.py` callback handler:

- Remove the `@dimagi.com` enforcement
- Any successfully-authenticated Connect user gets a `User` row created
- New users land at `/welcome` (no workspace yet) instead of `/opps`
- The dev-only `/auth/test-login/` flow is unchanged
- The bot identity flow (`/auth/e2e-login/` for `ace@dimagi-ai.com`) is
  unchanged; the bot user is added to the seeded "Dimagi Team"
  workspace as Editor in the migration step

The CommCare Connect OAuth scope and PKCE flow stay exactly as they are
today. The only change is the post-callback gate.

### 4.5 CLI integration: implicit-by-folder

The `ace` plugin (in `../ace`) does not change. It writes to whatever
Drive folder its local `.ace/config.yaml` points at, just as it does
today.

The web app indexes workspaces by `drive_root_folder_id` (unique). When
ace-web sees a Drive operation referencing folder X, it resolves
`Workspace.objects.get(drive_root_folder_id=X)` and treats that as the
operation's workspace. Membership-gated reads then apply normally.

The two CLI-side touch points stay path-compatible:

- **`/ace:run --ace-web-url <url>` transcript upload**
  (`apps/ingest/views.py` + the `upload-transcript` skill in the
  plugin). Today the upload payload includes `opp_slug`. We extend it
  with `ace_root_folder_id` — the plugin already knows this value from
  its local `.ace/config.yaml` (or per-opp config), so this is a
  one-line counterpart change in the plugin's `upload-transcript`
  skill, documented in Phase A's implementation plan as a paired
  ace + ace-web change. The web side resolves
  `Workspace.objects.get(drive_root_folder_id=<value>)` and validates
  the uploading user is a member.

  Backward compatibility: when an upload arrives without the new field
  (older plugin versions, ad-hoc curl uploads), the request is
  accepted and stored as an **orphan upload** — `IngestUpload.workspace`
  set to null, visible only to the uploading user in the `/sessions`
  Imported tab. This is the same fallback path orphan uploads already
  take today; it just becomes user-scoped instead of global.
- **The `ace-drive` SA's per-call `on_behalf_of`**
  (`apps/opps/drive_client.py:239`) — unchanged. The registry's
  impersonation grants are independent of workspace membership.

### 4.6 Onboarding flow (web-only third party)

```
Sign in via Connect OAuth
   │
   ▼
/welcome   (new page, shown when user has zero workspace memberships)
   │
   ├── "Create a workspace"
   │     │
   │     ▼
   │   Step 1 — Name your workspace
   │   Step 2 — Connect your Google Drive folder
   │     • UI shows: "Share this folder with: ace-drive@…iam.gserviceaccount.com (Editor access)"
   │     • Field: paste Drive folder ID OR URL (URL is parsed)
   │     • [Verify access] → POST /verify-drive-access/
   │         pass: shows up to 5 sample child names, "Continue" enabled
   │         fail: specific error ("not shared," "not a folder," "not found"); user fixes and retries
   │   Step 3 — Invite teammates  (skip allowed)
   │     • Email + role rows; sends invite email per row
   │     ▼
   │   Workspace created → redirect to /w/<slug>/opps
   │
   └── "Accept a pending invite"
         (visible only when WorkspaceInvite.email matches my Connect email)
         → POST /api/invites/<token>/accept/
         → redirect to /w/<slug>/opps
```

After onboarding, the persistent nav grows a **workspace switcher**
(top-left, before the page title). Switching just changes the URL
prefix; everything else (chat, opps, system, settings) is workspace-
scoped through the URL.

### 4.7 URL structure

Existing routes pivot from global to workspace-scoped:

| Today                     | After spec                          |
|---------------------------|-------------------------------------|
| `/opps`                   | `/w/<slug>/opps`                    |
| `/opps/<oppSlug>`         | `/w/<slug>/opps/<oppSlug>`          |
| `/sessions`               | `/w/<slug>/sessions`                |
| `/chat/<id>`              | `/w/<slug>/chat/<id>`               |
| `/system`                 | `/w/<slug>/system` (or workspace-agnostic — see below) |
| `/settings`               | `/settings` (user-level, not workspace-scoped) |
| `/share/<token>`          | `/share/<token>` (unchanged; token resolves to workspace internally) |

The legacy bare `/opps`, `/sessions`, `/chat/<id>` paths redirect to
`/w/<defaultSlug>/...` where `defaultSlug` is the user's most-recent or
only workspace, preserving deep links from the pre-multi-tenant era.

The System Overview tab (`apps/system/`) reads from the vendored ACE
plugin and is fundamentally workspace-agnostic. We move it to
`/system` (top-level, outside any workspace), available to any
authenticated user.

### 4.8 Migration

The team's web data is currently single-user (jjackson@dimagi.com is the
only person who has touched the web product to date). The migration is
therefore very simple:

A Django data migration runs once on deploy:

1. Create `Workspace(slug="dimagi-team", display_name="Dimagi Team",
   drive_root_folder_id=settings.ACE_DRIVE_ROOT_FOLDER_ID)`.
2. Add `jjackson@dimagi.com` (the founding user) as `Owner`.
3. Add the `ace@dimagi-ai.com` automation bot as `Editor`.
4. Backfill `OppWorkspace.workspace_id` for every existing row → the
   dimagi-team workspace.
5. Backfill `Session.workspace_id` for every opp-tied session via
   `opp_slug` lookup. Free chats stay null (creator-only visibility).
6. Backfill `IngestUpload.workspace_id` similarly when the upload
   references an opp; otherwise null.

After migration, `ACE_DRIVE_ROOT_FOLDER_ID` is consulted only as a
deployment hint by the migration itself. The runtime no longer reads
it. We can remove the env var from `task-definition.json` once the
migration has run on prod.

### 4.9 Audit and access logging

`apps/service_accounts/models.py — AccessLog` already records every SA
credential use with arbitrary `context` JSON. We extend the `context`
payload from opp/session views with `{"workspace_slug": ...,
"actor_email": ...}` so per-workspace activity can be reconstructed
from the existing log table without new infrastructure.

No new "workspace activity log" table in v1. If we later want a
user-visible activity log, the data is already there.

## 5. Error handling and edge cases

- **Folder ID collision on workspace create.** Schema-level UNIQUE on
  `drive_root_folder_id` returns a clean 409 with body
  `{error: {code: "folder-already-claimed", message: "...", existing_workspace_slug: "..."}}`.
  The UI shows: "This folder is already connected to a workspace
  (`<workspace_name>`). Ask the workspace owner to invite you, or pick
  a different folder."
- **Slug collision on workspace create.** Auto-suffix with `-2`, `-3`
  etc. until unique (matches the existing opp-creator pattern at
  `apps/opps/opp_creator.py:54`).
- **SA loses access to a folder mid-session** (user revokes share in
  Drive UI). Drive API call fails with 404; `_require_drive` returns
  a 503 envelope `{error: {code: "drive-access-lost", ...}}`. The
  Workspace settings page surfaces a "Drive access broken" banner with
  a link to re-verify.
- **Last owner removes themselves.** Blocked at the API layer. UI
  shows "You're the last owner; promote another member to owner first."
- **Invite to an email that's already a member.** 409 with code
  `already-member`.
- **Invite-accept races.** A single pending invite can only be
  accepted once (`accepted_at` is set inside a transaction with
  `select_for_update`). Subsequent attempts return the existing
  membership.
- **Workspace deletion when opps still exist in Drive.** Soft-delete
  the workspace row + cascade-soft-delete its OppWorkspace rows. Drive
  artifacts are NOT touched (the user can re-attach later via a new
  workspace pointing at the same folder ID; uniqueness is on
  *non-deleted* rows).

## 6. Testing

Unit tests (`pytest`):

- Workspace model: slug uniqueness, role transitions, last-owner
  protection
- Membership: role-based permission decorators
- Invite token: uniqueness, expiry, single-use semantics
- `verify-drive-access` view: pass case, "not shared" case, "not a
  folder" case, "folder doesn't exist" case
- Migration: idempotency, opp/session backfill correctness
- API scoping: a member of workspace A cannot see opps from workspace B
  (404, not 403)
- CLI implicit-folder linkage: an upload with a folder ID belonging to
  workspace B is correctly attributed even when the uploading user is
  the bot identity

Integration tests:

- End-to-end onboarding flow via the existing `/auth/e2e-login/` bot
  account: create workspace → verify folder access (against a fake
  Drive client) → invite → accept-invite (as a second test user) →
  see opps
- Backward-compat for legacy URLs: `/opps` redirects to
  `/w/dimagi-team/opps` for the founding user

Existing `apps/opps/tests/` need to be reworked to seed a workspace +
membership in `setUp` (or via a `pytest` fixture) and assert against
workspace-scoped paths. Most can be mechanically updated.

## 7. Implementation phasing

Three sequential plans, each ships a coherent slice. Each one lands on
`main` independently and is usable end-to-end on its own.

### Phase A — Data model + scoped reads

- New `apps/workspaces/` app: models, migration, admin
- Drop `@dimagi.com` filter at `apps/auth/oauth_views.py:112`
- One-shot data migration: create `dimagi-team` workspace, seed
  founding membership, backfill opp/session/upload FKs
- Workspace-scoped URL prefix (`/w/<slug>/...`) on the frontend; legacy
  `/opps` etc. redirect to the user's default workspace
- Membership-gated reads on every existing opp/session/upload endpoint
- Minimal nav: workspace switcher dropdown
- API: `GET /api/workspaces/`, `GET /api/workspaces/<slug>/`,
  membership scoping on opp/session views
- No invite/share UI, no workspace-creation UI; admins use Django admin
  for the (rare) manual workspace setup before Phase B

After Phase A: existing single-user product behaves identically; the
multi-tenant plumbing is in place but invisible to end users.

### Phase B — Onboarding, sharing, verification

- `/welcome` page for users with zero memberships
- Workspace creation wizard (3 steps; § 4.6)
- `POST /api/workspaces/`, `POST /api/workspaces/<slug>/verify-drive-access/`,
  `GET /api/workspaces/drive-config/`
- Member management UI on workspace settings
- Invite + accept flow: create invite, send email via the existing
  `ace@dimagi-ai.com` mailer, accept-invite landing page
- Folder-already-claimed and other error UX from § 5

After Phase B: a third-party user can sign in, create a workspace, and
invite teammates entirely from the web.

### Phase C — Polish + edge cases

- Move-opp-between-workspaces (owner-only)
- Leave-workspace UX
- Audit log surfacing on workspace settings (read-through to
  `AccessLog` filtered by workspace context)
- Drive-access-broken banner + re-verify action (§ 5)
- Forward-compat hooks for per-workspace SAs (schema only — provider
  registry already supports it)

After Phase C: the multi-tenancy story is complete; remaining work
(per-user CLI tokens, per-workspace SAs, SSO) is scoped as separate
specs.

The scout proposals P2 (stale empty-state copy) and P3 (SA email +
verify-drive-access diagnostic) are absorbed into Phase B; they don't
ship standalone.

## 8. Open questions

- **Email delivery for invites.** The `ace@dimagi-ai.com` Gmail mailer
  in the ACE plugin works fine for opp/LLO emails; reusing it for
  workspace invites is the path of least resistance, but it ties
  ace-web to an ACE-plugin-shaped piece of infrastructure for a
  product feature that should be ace-web-native. Phase B can ship
  with a copy-paste invite link first (no email send) if the mail
  integration becomes a blocker.
- **Personal workspace vs no workspace.** A user with zero memberships
  who isn't accepting an invite has only one option: create a
  workspace. We do not auto-create a "Personal" workspace. This is
  intentional — every workspace requires a Drive folder, and we don't
  want to silently make Drive folders for users who haven't asked for
  one. Revisit if the friction is real.
- **Display-name uniqueness.** Slug is unique; display_name is not.
  Two workspaces named "Smoke Test" can coexist (distinguished by
  slug + creator). Acceptable for v1.

## 9. Files touched

New:
- `apps/workspaces/__init__.py`, `models.py`, `views.py`, `urls.py`,
  `admin.py`, `serializers.py`, `permissions.py`, `migrations/0001_initial.py`,
  `migrations/0002_seed_dimagi_team.py`, `tests/`
- `frontend/src/pages/WelcomePage.tsx`, `WorkspaceCreatePage.tsx`,
  `WorkspaceSettingsPage.tsx`, `InviteAcceptPage.tsx`
- `frontend/src/components/WorkspaceSwitcher.tsx`
- `frontend/src/api/workspaces.ts`

Modified:
- `apps/auth/oauth_views.py` — drop `@dimagi.com` check, redirect new
  users to `/welcome`
- `apps/opps/models.py` — `OppWorkspace` gains `workspace` FK
- `apps/opps/views.py` — workspace-scoped reads + writes
- `apps/sessions/models.py` — `Session` + `ShareToken` workspace FKs
- `apps/ingest/views.py` — set `workspace` on upload
- `apps/opps/opp_creator.py` — workspace-scoped slug uniqueness
- `apps/opps/drive_client.py` — `get_drive_client` takes optional
  workspace context for the AccessLog payload
- `config/settings/base.py` — `ACE_DRIVE_ROOT_FOLDER_ID` reduced to a
  migration hint (commented as such)
- `frontend/src/router.tsx` — workspace-scoped URL prefix + legacy
  redirects
- `frontend/src/pages/OppListPage.tsx` — workspace-scoped data; empty
  state copy fix (Phase B)
- `frontend/src/pages/SettingsPage.tsx` — user-level only; SA email
  surfacing moves to WorkspaceSettings (Phase B)
- `CLAUDE.md` — describe the workspace concept, the migration, and
  the implicit-by-folder CLI linkage
- `README.md` — rewrite first-run section for web-only users
