# Per-opp tenancy, opp-bound ACE sessions, clone-to-new-workspace, and release

**Date**: 2026-09-28
**Status**: Built and deployed 2026-09-28 (see "As built" at the end); open items listed there
**Owner**: Jonathan Jackson
**Commands**: `clone-to-new-workspace` (mechanical, generic) and `release`
(external-facing steps on top); working names
**Spans**: ace-web (this repo) and the ACE plugin (`dimagi-internal/ace`)
**Background**: ACE's design doc "External reviewer access to ACE runs — design v1"
(Google Doc `1DMFXXUikPo_e-UU3zT7Zq8CQ6OMFPKKtna00VWGLmio`, from the ACE turn
on the "Connect + Spark" thread, 2026-09-28)

## Why

Spark Microgrants were the first external team to review an ACE run
(`spark-facilitator/20260926-1413`). What they could and could not open showed
that ACE's access model only works for Dimagi staff.

1. **They cannot sign in to ace-web.** Connect OAuth is the only sign-in, and
   production rejects any email outside `ACE_ALLOWED_EMAIL_DOMAINS` before an
   account exists (`apps/auth/oauth_views.py`), so an invite to a Spark address
   can never be accepted.
2. **Every access grant we use exposes every ACE run.** ACE builds everything
   in shared tenants: one HQ project space (`connect-ace-prod`), one Connect
   network-manager org, one OCS team, and Labs synthetic opps limited to Dimagi
   domains. HQ App Editor, Connect org viewer and OCS Chatbot Admin each open
   every opp in the tenant.
3. **The shared tenants are not modelled anywhere.** They are hard-coded in
   ACE's `.env` (`ACE_HQ_DOMAIN`, `connect_orgs`, `OCS_TEAM_SLUG`), so "where an
   opp's assets live" is an accident of whose machine ran it rather than a
   property of the opp.

Building in shared tenants is right while ACE iterates. When a run is ready for
a real external review, its assets should move into areas that belong to that
reviewer, so they can be given access that shows only their own things. **The
end state is what the partner would have if they had built and configured
everything themselves, instead of ACE.**

## Decisions (Jonathan, 2026-09-28)

- **Invite-only login.** ace-web admits invited people from outside the domain
  list. We do not add each partner's domain to the list.
- **Partners get their own areas.** That means their own HQ project space,
  Connect orgs and Labs scope.
- **No OCS account for reviewers** (2026-09-28). OCS permissions are team-wide
  (no per-chatbot grant: Chatbot Admin can edit every bot on the team, Chat
  Viewer reads every bot's transcripts), so reviewers chat through the bot's
  public link, which needs no login and exposes nothing else. The bot stays on
  ACE's team; a per-partner OCS team is only for a partner taking the bot over.
- **Whether to create Connect program-manager orgs per partner is open**
  (Jon is checking, 2026-09-28). The Connect clone step waits on it.
- **Where an opp's assets live is stored per opp, not per tenant.** It is
  normally the same for every opp in a workspace.
- **One model for everyone.** Dimagi's opps use the same model. Nothing is
  special about Dimagi; it is how ACE works.
- **One ACE agent.** ACE must lock itself to the opp and workspace it is
  operating on. Separate ACE agents are deferred; see "One agent, and when that
  stops being enough".
- **Stored in ace-web's database.** Tenancy lives there, not in `opp.yaml` in
  Drive.
- **Anonymous editing is out of scope.** Anonymous editing of the public
  summary will be removed entirely once this system is in place.
- **Clone and release are separate commands.** Clone is the generic
  mechanical copy into a new workspace and tenancy. Release is a second step
  that adds audit, invites, redirect and polish for outside reviewers.
- **ACE merges its own PRs** as the work iterates.

## Concepts

### Tenancy

Tenancy is where an opp's assets live in each system:

```yaml
drive_root_folder_id: <folder>        # the workspace Drive root the opp sits under
hq_domain: connect-ace-prod
connect_pm_org: <slug>                # program-manager org (ACE is admin)
connect_holding_org: <slug>           # org that holds the opportunity
ocs_team: <slug>
labs_allowed_domains: ["@dimagi.com", "@dimagi-ai.com"]
```

- **Every opp has one** (`OppWorkspace.tenancy`).
- **Workspaces have a default** (`Workspace.default_tenancy`), copied into each
  new opp when it is created. After that the opp's copy is the truth: changing
  the default does not rewrite existing opps.
- **Owners set it.** It is set by workspace owners through ace-web's API and
  Workspace Settings, and every change is written to the workspace audit log.
  Tenancy decides where ACE may *write*, so it belongs under ace-web's roles.
  It must not live in a Drive file that ACE itself edits on every run.
- **Reviewers are not part of tenancy.** Who may *see* the opp is the
  workspace member list, which ace-web already has.
- **A backfill gives existing opps their tenancy.** A data migration sets
  `dimagi-team`'s default, and every existing opp's tenancy, to today's `.env`
  values. ACE then stops reading those values from `.env`.

### Opp-bound sessions

An ACE session that acts on an opp is **bound** to that opp. The binding comes
from whatever launches the session, not from the agent:

- `apps.canopy.run_dispatch` (programmatic runs);
- canopy turn metadata (`opp_slug`, `workspace`);
- `/ace:run`'s preflight (laptop runs).

At bind time, ACE fetches the opp's tenancy from ace-web (PAT or canopy
delegation) and records a copy in `run_state.yaml` (`tenancy:`), so each run
shows which tenancy it used.

**Where the guard lives: a PreToolUse hook, not the MCP servers** (changed
while building, 2026-09-28). The MCP servers have no common dispatch point
(`ace-connect`'s wrapper sees no arguments; `ace-gdrive` has ~47 hand-written
handlers), and connect-labs is a remote server nothing in-process can see. A
plugin PreToolUse hook is the one choke point every ACE tool crosses, and
Claude Code gives it the session id. So:

- **Binding** is `bin/ace-bind <ws>/<opp>`: it fetches the opp's tenancy and
  writes `~/.ace/opp-bind/<session id>.json` (keyed by
  `$CLAUDE_CODE_SESSION_ID`). It can happen mid-session, after the opp is
  resolved.
- **The guard** (`hooks/tenancy_guard.py`, targets in
  `config/tenancy-targets.json`) checks each ace-connect / ace-ocs /
  connect-labs **write**: HQ `domain` / `downstream_domain`, Connect
  `organization_slug` / `target_organization_slug` / apps' `cc_domain`, Labs
  `allowed_domains`, and — because OCS's team is fixed at server start — the
  install's `OCS_TEAM_SLUG`. Source arguments (`upstream_domain`) are not
  checked: reading from the shared space into a partner's is how a clone
  works. A tenancy field that is not set up refuses rather than guesses.
- **Unbound sessions are allowed and logged** (`unbound-writes.log`).
- **Warn mode (rollout).** `/ace:run`, `/ace:step` and `/ace:turn` bind with
  `--warn`: a would-be refusal is recorded in `bound-violations.log` and let
  through, because older runs wrote to Connect orgs the backfill doesn't list
  (the legacy PM org `ai-demo-space`). Clone and release bind in enforce mode.
  Flip the run entry points to enforce after reading that log.
- **Drive** is checked inside the ace-gdrive / ace-decisions servers
  (`lib/drive-tenancy-guard.ts`): a bound session's Drive write must target
  something inside the opp's folder (parent-chain walk from the workspace
  Drive root `ace-bind` records). The hook can't: it is stdlib-only.
- **Still to do:** in-server defaults from tenancy instead of `.env`, and
  scoped credentials (domain-scoped HQ key).

**Inbound turns (`/ace:turn`)** can touch several opps in one turn. The turn
triages while unbound (read-only), then sends each act-tier action to a session
bound to that thread's opp. This matches how inbox-triage already processes one
thread at a time.

### One agent, and when that stops being enough

The binding and guard stop **mistakes**: a wrong default, another opp's id
pasted in, one partner's work leaking into another's area. They cannot stop a
**compromised** ACE. `ace@` is still an admin in every tenancy, so a session
that got around its own MCP guard could reach any of them.

A separate ACE agent means a separate identity with its own credentials. It
becomes necessary when a partner needs the guarantee that "no identity that
can reach our tenancy can reach anyone else's". That is a contractual or
data-protection bar, not a convenience one.

Because every credential and target resolves from the bound tenancy, splitting
later means pointing one tenancy at a different identity, not rewriting skills.

## ace-web changes

### A. Invite-only login

The domain gate in `oauth_callback` admits a sign-in when **any** of these is
true:

- the email's domain is in `ACE_ALLOWED_EMAIL_DOMAINS` (unchanged);
- the email has a **pending** `WorkspaceInvite` (not accepted, revoked or
  expired);
- the email already belongs to a user with **at least one**
  `WorkspaceMembership`.

**Why the third rule is required:** accepting an invite marks it used, so
without this rule a partner could sign in once and never again. Removing
someone's last membership also removes their sign-in, which is the right way to
cut off a partner.

**Details:**

- Emails are compared lower-cased.
- A rejected sign-in keeps today's message and adds: "If you were invited, sign
  in with the email address the invite was sent to."
- The User row is created only **after** the gate passes, so a rejected
  outsider leaves nothing behind.
- A sign-in admitted by invite or membership (not by domain) logs which rule
  admitted it.

**The partner's path:**

1. The owner invites the partner's HQ email.
2. The partner opens `/invite/<token>`.
3. They choose "Log in with CommCare HQ" at Connect, which creates their
   Connect identity in one step.
4. They return to ace-web and accept the invite.

The invite page tells partners to use "Log in with CommCare HQ" *first*. Someone
who accepts a Connect invite before ever signing in with HQ gets a password
account, and HQ sign-in then fails for them.

### B. Tenancy

- **Model:** a migration adding `OppWorkspace.tenancy` and
  `Workspace.default_tenancy` (JSONField, default `{}`), validated by one
  Pydantic `Tenancy` schema with every field optional.
- **Copy on create:** opp creation (`opp_creator.py` and the lazy `OppWorkspace`
  creation paths) copies the workspace default into the new opp.
- **Read API:** `GET /api/w/{ws}/opps/{slug}/tenancy`, available to members. It
  is what ACE fetches at bind time.
- **Write API:** `PATCH /api/w/{ws}/opps/{slug}/tenancy` and `PATCH
  /api/workspaces/{slug}` (`default_tenancy`), owner-only and audit-logged.
- **UI:** Workspace Settings gets a "Default tenancy" panel, and the opp gets a
  read-only tenancy line, editable by owners.
- **Backfill:** a data migration sets `dimagi-team`'s default and every
  existing opp's tenancy from explicit constants in the migration (today's
  `.env` values). It fills only empty fields, so it never overwrites operator
  edits.

### C. Copying a run into another workspace

- **Endpoint:** a new endpoint copies a run into another workspace. The caller
  must be an owner of both workspaces; to anyone else, either workspace returns
  404. **It returns 202 and copies on a background thread** — callers poll
  `…/clones`. The first real clone (347 files) took ~14 min at ~2.4 s per file;
  in-request, it 504'd at the load balancer at 10 min (ace-web#823).
- **Not a fork:** it copies the run whole — every phase folder, including the
  Phase 6 screenshots and videos a reviewer needs (a fork skips them) — except
  ACE's email records (`comms-log/`, `*_comms-log`): internal, and ACE routes
  inbound mail by the thread ids in them. `run_state.yaml` is copied first, as
  in a fork (ace-web#734).
- **Destination:** the copy lands under the target workspace's Drive root as
  `<opp-slug>/runs/<run-id>/`, with the same run id. The first clone of an opp
  into a workspace also copies its opp-level files — an allowlist (`opp.yaml`,
  `idea.md`, `pdd.md`, `inputs/`), because the opp root also holds ACE's
  working notes (ace-web#822); later runs reuse them. An `OppWorkspace` row is
  created in the target if needed, with tenancy taken from the **target
  workspace's default**. A run already in the target is a 409 — unless its
  last clone record is `error`, or `copying` with no progress for 10 minutes
  (its worker died): then the partial run is trashed and the clone restarts.
- **Products:** the copied run's `products` blocks still point at the source
  tenancy's assets until the ACE command rewrites them system by system.
- **Record:** a `RunClone` row (source, target, opp, run, status, files,
  error, who) — in ace-web's database, NOT the source run's `run_state.yaml`,
  so the source is never written to. `GET …/runs/{run}/clones` lists them.
- **Redirect (enabled by `release`, not by the clone):** the source run's
  public summary endpoint can redirect (HTTP 308) to the released clone's
  summary. The link Spark already has therefore lands on their copy.
- **Workbench:** internal users see a banner linking to the released copy
  instead of being redirected.
- **Cache:** the target workspace's opp cache is cleared after a clone (a
  new child of the root is a listing the Drive Changes feed does not reliably
  report).

## ACE changes (`dimagi-internal/ace`)

### D. Opp binding and the tenancy guard

This is the foundation, and it is valuable before any partner exists.

- **v1 (ace#2530):** `bin/ace-bind` + the PreToolUse tenancy guard, described
  under "Opp-bound sessions"; unbound sessions allowed and logged.
- **Next:** wire `/ace:run`, `/ace:turn` and ace-web run dispatch to bind
  (needs `connect_pm_org` set on `dimagi-team`'s opps first — a bound session
  refuses Connect writes while it is unset); then refuse unbound writes; then
  Drive, in-server tenancy defaults, and scoped credentials.
- **Tests:** `test/hooks/tenancy-guard.test.ts` spawns the real hook and
  `bin/ace-bind`.

### E. `/ace:clone-to-new-workspace <opp>/<run-id> --to <workspace>`

A generic clone with nothing partner-specific in it. It works on a completed
run, leaves the source untouched (the clone is a `RunClone` row), sends no
invites, and adds no redirects.

1. **Preflight.**
   - Resolve the target workspace's default tenancy.
   - Check every one-time setup item in each system.
   - If anything is missing, stop **before creating anything** and list what a
     human must do (e.g. "Connect staff: create program-manager org `spark` and
     add ace@dimagi-ai.com as admin").
2. **Clone.**
   - ace-web copies the run (C).
   - ACE binds a session to the **new** opp and rebuilds each system's assets
     there, one step per system. Binding to the new opp means the guard itself
     stops a step from writing into the source tenancy.
   - Each step records what it created in a `clone` block, in both runs'
     `run_state.yaml`.
3. **Report.** Per system: created, or NOT DONE with the reason. Each line has
   a read-back proving it (id, URL).

**Always rebuild, even when the tenancies match.** An opp's products belong to
that opp. Otherwise two opps in two workspaces would share one Connect
opportunity, and a grant on one would expose the other.

**Resumable and idempotent.** A step whose `clone` entry is complete is skipped
on rerun. A step that may have succeeded without confirming it (the HQ app copy
often times out after making the copy) re-lists before retrying, because a
blind retry creates a duplicate.

Each of the per-system steps below ships on its own.

**HQ**

- Create `hq_domain` if it doesn't exist (`commcare_create_domain`).
- Copy Learn and Deliver with `commcare_linked_app_copy(linked:false)`. This is
  an unlinked copy, so no Pro Edition is needed; the copy keeps the camera-only
  and grid-menu settings.
- Build and release (`commcare_make_build`, `commcare_release_build`), and
  record the `hq_app_id`s.
- **Not in v1:** mobile workers. There is no tool to create them, so the report
  lists them as a manual step.
- **First live check:** a cross-space unlinked copy has only been tested within
  one space. The first clone verifies it on Spark before anything else is
  built on top of it.

**Connect**

- **Preflight requires** both orgs to exist with ACE as admin, and the holding
  org to have an accepted program application. There is no create-org tool, so
  Connect staff set this up once per tenancy.
- **As built:** the clone re-runs Phase 4 (`connect-setup`) against the
  cloned run with `connect_orgs` from the tenancy, after clearing the copied
  `opp.yaml` `connect:` block (it names the source program, which Phase 4
  would otherwise reuse). The same skills that built the source build the
  clone's program and opportunity, pointing at the rebuilt HQ apps.

**Labs**

- **As built:** a run's labs-only opps, program, registry and dashboards were
  created for that run alone, so the clone does NOT rebuild them — it adds the
  tenancy's domain to each opp's allowlist with the new connect-labs tool
  `synthetic_set_allowed_domains` (connect-labs#2100; creator or Dimagi staff
  only, refuses an empty list). Source and clone share the same labs assets.
  Replaying the cascade would regenerate data, registry, reports and 13 weeks
  of history from manifests ACE may not archive.

**OCS — not rebuilt**

- The bot stays on ACE's team and the copied `products.ocs_chatbot` is kept.
  Reviewers use its `public_url` (no account). The clone records
  `clone.ocs: {status: kept, reason: public-link}` (ace#2532).
- `ocs_team` stays in the tenancy schema for a later handover step (a partner
  running the bot themselves), which would rebuild the bot in their team.

### E2. `/ace:release <opp>/<run-id> --reviewers <email[:role]>,...`

Run on the clone, when someone outside is about to review it. It needs no
clone: a Dimagi-internal run can be released to Dimagi reviewers. A clone is
needed only when the reviewers must not see the rest of the tenancy.

**Everything is set up before anyone is invited.** Reviewers are not members
of the workspace during the clone or the release, so nothing half-built is
ever visible to them. Invites are the last step, and the ace-web workspace
invite is the very last.

1. **Audit.**
   - Run `run-surface-audit` on the run.
   - Stop if the audit finds anything broken.
2. **Polish.** An open list, grown as external reviews teach us. Starting
   ideas:
   - strip internal-only links and notes from the public summary;
   - regenerate screenshots that show shared-tenant URLs.
3. **Redirect (optional).**
   - When the source run's summary link has already been sent, the source's
     public summary 308-redirects to the released run (ace-web C).
   - Internal users see a banner in the Workbench instead of being redirected.
4. **Invite, last.** Every invite is approved first, shown together as one
   list. This absorbs `share-run-access`'s grant step (F).
   - First, access in each system, limited to the opp's tenancy:
     - HQ: `commcare_invite_web_user` (App Editor is acceptable, because the
       space holds only this tenancy's apps).
     - Connect: `connect_add_org_member` (viewer).
     - OCS: **no account** — the bot's public link goes in the invite email.
     - Labs: `labs_allowed_domains` already covers access.
   - Then the ace-web workspace invite (A), with an email that carries the
     "Log in with CommCare HQ first" steps.
5. **Record.**
   - `released: {at, by, to: [emails]}` in `run_state.yaml`.
   - The Workbench shows it.

### F. share-run-access

- Fix ace#2525.
- It keeps its job of granting access within an opp's *current* tenancy.
- It refuses to grant a non-member of the opp's workspace access to a tenancy
  shared with other workspaces, and points at `clone-to-new-workspace`
  instead.
- Its grant step is absorbed by `release` (E2), leaving `share-run-access`
  as a thin wrapper or retiring it.

## What each system can do (research, 2026-09-28)

| System | Create a new area | Move assets | Copy / recreate | Scoped invite |
|---|---|---|---|---|
| ace-web | yes (workspace) | yes, Drive | yes | yes, after A |
| HQ | yes, `commcare_create_domain` | no | app copy across spaces | yes |
| Connect | **no** (manual org) | **no** (holding org fixed at creation) | recreate program + opp | yes |
| OCS | **no** (manual team) | **no** (clone stays in-team) | not needed: public link | team-wide only — not used |
| Labs | n/a | no allowlist update | clone with new allowlist | email domain only |

## Build order

Each item is its own PR, merged when green.

1. ace-web **A**: invite-only login. On its own this lets Spark sign in to a
   workspace.
2. ace-web **B**: tenancy model, API, and the `dimagi-team` backfill.
3. ACE **D**: opp binding and the tenancy guard, with `.env` defaults retired.
4. ace-web **C**: copying a run into another workspace, and the redirect.
5. ACE **E**: clone skeleton (preflight, `clone` block, report), then HQ.
6. ACE **E**: Connect (re-runs Phase 4 in the tenancy's orgs).
7. ACE **E**: Labs.
8. ~~ACE **E**: OCS~~ — dropped: reviewers use the public link.
9. ACE **E2**: `release` (audit, invites, redirect, record), absorbing
   **F**.

**First use: Spark.**

1. Create the `spark` workspace and set its default tenancy.
2. Create Spark's Connect program-manager and holding orgs with ace@ as
   admin (how per-partner PM orgs get created is Jonathan's open decision).
3. Clone `spark-facilitator/20260926-1413` into `spark`.
4. Run `release` on the clone with Anne, Sasha, Rachel and Enock as reviewers.
   It audits, polishes and redirects the link they already have, then invites
   them in each system, and last of all to the `spark` workspace.

## Testing

- **A:** unit tests on the gate (`apps/auth/test_login_views.py`):
  - admitted by domain;
  - admitted by a pending invite (case-insensitive);
  - admitted by membership;
  - rejected for an expired, revoked or accepted invite when the user has no
    membership;
  - rejected with no invite, with no User row created;
  - an empty domain list is unchanged.
- **B:**
  - schema validation;
  - owner-only PATCH with an audit row;
  - copy-on-create;
  - the backfill fills only empty fields.
- **C:**
  - the copy endpoint, with a faked Drive client as in the `opp_forker` tests;
  - the redirect appears only once complete;
  - a non-owner gets 404.
- **D:** see D.
- **E:**
  - dry-run mode per step;
  - rerun idempotence from a recorded `clone` block;
  - HQ verified live on Spark first.
- **After deploy:** run `scripts/qa/labs_probe.py`.

## Out of scope

- Removing anonymous editing on the public summary (a separate, later change).
- Automating Connect org and OCS team creation, which needs upstream APIs.
- Per-user (rather than per-domain) Labs access.
- Separate ACE agents or identities per tenancy (see "One agent, and when that
  stops being enough").
- Keeping a clone in sync with later source runs. Cloning a newer run is
  another invocation.

## As built (2026-09-28)

| Piece | PR | Deployed |
|---|---|---|
| A. Invite-only login | ace-web#810 | yes |
| B. Per-opp tenancy + backfill (`ace-pm-org`, `ace-nm-org`, `connect-ace-prod`) | ace-web#811, #818 | yes |
| Default tenancy Settings panel | ace-web#815 | yes |
| C. Clone a run into another workspace | ace-web#812 | yes |
| Release record + source-link forwarding | ace-web#814 | yes |
| Workbench "copied to" banner | ace-web#817 | yes |
| D. `bin/ace-bind` + PreToolUse tenancy guard | ace#2530 | plugin (ace-web refreshes it on boot) |
| D. Warn mode; `/ace:run`, `/ace:step`, `/ace:turn` bind | ace#2540 | plugin |
| D. Drive guard in ace-gdrive / ace-decisions | ace (follow-up) | plugin |
| E. `/ace:clone-to-new-workspace` (HQ, Labs, Connect; OCS kept) | ace#2531, #2533, #2542 | plugin |
| E2. `/ace:release` | ace#2534 | plugin |
| OCS: no reviewer accounts | ace#2532 | plugin |
| Labs `synthetic_set_allowed_domains` | connect-labs#2100 | yes |

**Open:**
- How per-partner Connect program-manager orgs get created (Jonathan: a new
  prod permission so ACE can create PM orgs without being a global admin).
- Flip `/ace:run` / `/ace:turn` from warn to enforce after reviewing
  `bound-violations.log`; correct any opp whose runs used `ai-demo-space`.
- Not yet exercised end to end on a real partner: the first Spark clone is the
  live test (cross-space HQ app copy has only been live-tested within one
  project space).
