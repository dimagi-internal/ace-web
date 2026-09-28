# Per-opp tenancy, opp-bound ACE sessions, and release-to-new-workspace

**Date**: 2026-09-28
**Status**: Approved in conversation (Jonathan, 2026-09-28), spec under review
**Owner**: Jonathan Jackson
**Command name**: `release-to-new-workspace` (working name)
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
  Connect orgs, OCS team and Labs scope.
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
- **Release is its own command,** run on a completed run.
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

ACE's MCP servers (connect, ocs, gdrive, mobile) load the bound tenancy when
they start and **guard every call**:

- **Explicit targets are checked.** A call that names a domain, org, team or
  Drive folder is checked against the tenancy and refused with a typed
  `outside_bound_tenancy` error if it points anywhere else.
- **Missing targets default to the tenancy.** A call that names no target uses
  the tenancy's value. Today it falls back to `.env`.
- **Shared templates are read-only.** Reads of shared templates (the OCS golden
  template, deck stencils, the connect-baseline screenshots) go through an
  explicit read-only allowlist.
- **Credentials are scoped where the system allows it.** OCS tokens are per
  team, and HQ API keys can be limited to one project space. A session loads
  only the bound tenancy's keys, so even a buggy tool cannot reach another
  tenancy. Connect only has a user-level token, so there the guard is the only
  protection.
- **An unbound session is read-only** across opps.
- **The existing HQ guard is folded in.** `assertAceOwnedHqDomain`
  (`lib/destructive-guards.ts`) is the precedent; it becomes a special case of
  this guard.

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
  404.
- **Not a fork:** it copies the run whole. It reuses `opp_forker.py`'s Drive
  machinery: `run_state.yaml` is written first, then the bulk copy, retrying
  only on 429, with progress polling.
- **Destination:** the copy lands under the target workspace's Drive root as
  `<opp-slug>/runs/<run-id>/`, with the same run id. An `OppWorkspace` row is
  created in the target if needed, with tenancy taken from the **target
  workspace's default**.
- **Products:** the copied run's `products` blocks still point at the source
  tenancy's assets until the ACE command rewrites them system by system.
- **Forward link:** the source run records `released_to: {workspace, opp,
  run}`.
- **Redirect:** once the release's ace-web step is complete, the source run's
  public summary endpoint redirects (HTTP 308) to the released run's summary.
  The link Spark already has therefore lands on their copy.
- **Workbench:** internal users see a banner linking to the released copy
  instead of being redirected.
- **Cache:** both runs' snapshot caches are invalidated. `released_to` is an
  optional pass-through field, so `_KEY_VERSION` does not change.

## ACE changes (`dimagi-internal/ace`)

### D. Opp binding and the tenancy guard

This is the foundation, and it is valuable before any partner exists.

- **Bind a session.** Add a bind step to session start (the `/ace:run`
  preflight, and the turn and run-dispatch entry points). It fetches tenancy
  from ace-web and writes it to `run_state.yaml` and to the MCP servers'
  environment.
- **Guard the MCP servers.** Add the tenancy guard to each MCP server's tool
  dispatch, with the read-only template allowlist.
- **Retire the `.env` defaults.** Replace every `.env`-derived default target
  with the bound tenancy's value.
- **Scope credentials.** Load only the bound tenancy's credentials where they
  are per-tenant (OCS per-team token, a domain-scoped HQ API key).
- **Tests:**
  - every targeted tool refuses an out-of-tenancy target;
  - every untargeted tool resolves from tenancy;
  - an unbound session cannot write.

### E. `/ace:release-to-new-workspace <opp>/<run-id> --to <workspace>`

The command runs on a completed run and leaves the source run untouched. It has
four stages:

1. **Preflight.**
   - Resolve the target workspace's default tenancy.
   - Check every one-time setup item in each system.
   - If anything is missing, stop **before creating anything** and list what a
     human must do (e.g. "Connect staff: create program-manager org `spark` and
     add ace@dimagi-ai.com as admin").
2. **Release.**
   - ace-web copies the run (C).
   - ACE then binds a session to the **new** opp and recreates each system's
     assets there, one step per system. Binding to the new opp means the guard
     itself stops a step from writing into the source tenancy.
   - Each step records what it created in a `release` block, in both runs'
     `run_state.yaml`.
3. **Invite.**
   - Invite the target workspace's members to each system, with roles limited
     to the new tenancy.
   - Every invite is shown for approval before it is sent.
4. **Report.** Per system: created, invited, or NOT DONE with the reason. Each
   line has a read-back proving it (id, URL, member list).

**Resumable and idempotent.** A step whose `release` entry is complete is
skipped on rerun. A step that may have succeeded without confirming it (the HQ
app copy often times out after making the copy) re-lists before retrying,
because a blind retry creates a duplicate.

Each of the per-system steps below ships on its own.

**HQ**

- Create `hq_domain` if it doesn't exist (`commcare_create_domain`).
- Copy Learn and Deliver with `commcare_linked_app_copy(linked:false)`. This is
  an unlinked copy, so no Pro Edition is needed; the copy keeps the camera-only
  and grid-menu settings.
- Build and release (`commcare_make_build`, `commcare_release_build`), and
  record the `hq_app_id`s.
- Invite members with `commcare_invite_web_user`. App Editor is acceptable,
  because the space holds only this tenancy's apps.
- **Not in v1:** mobile workers. There is no tool to create them, so the report
  lists them as a manual step.
- **First live check:** a cross-space unlinked copy has only been tested within
  one space. The first run verifies it on Spark before anything else is built
  on top of it.

**Connect**

- **Preflight requires** both orgs to exist with ACE as admin, and the holding
  org to have an accepted program application. There is no create-org tool, so
  Connect staff set this up once per tenancy.
- Recreate the program in `connect_pm_org` and the opportunity targeting
  `connect_holding_org`. They point at the **new** HQ apps and reuse the source
  run's payment units, verification flags and dates.
- Invite members with `connect_add_org_member`, as viewer by default.

**Labs**

- Clone each synthetic opp in `synthetic.cascade` with `allowed_domains =
  labs_allowed_domains`. There is no tool to update the allowlist on an
  existing opp.
- Copy the run's workflows and dashboards onto the clones (`copy_workflow`) and
  rewrite `synthetic.*`.
- The finest access control available is an email domain.

**OCS**

- **Preflight requires** the team to exist and ACE to hold credentials for it:
  a login plus `OCS_API_TOKEN_<SLUG>`. There is no create-team tool.
- **Tools must change first.** The write tools need to resolve their team from
  the bound tenancy; today they only reach `OCS_TEAM_SLUG`. That comes with D.
- **The bot is rebuilt** from the source run's prompt, knowledge files and
  settings, then published. A clone cannot cross teams.

### F. share-run-access

- Fix ace#2525.
- It keeps its job of granting access within an opp's *current* tenancy.
- It refuses to grant a non-member of the opp's workspace access to a tenancy
  shared with other workspaces, and points at `release-to-new-workspace`
  instead.

## What each system can do (research, 2026-09-28)

| System | Create a new area | Move assets | Copy / recreate | Scoped invite |
|---|---|---|---|---|
| ace-web | yes (workspace) | yes, Drive | yes | yes, after A |
| HQ | yes, `commcare_create_domain` | no | app copy across spaces | yes |
| Connect | **no** (manual org) | **no** (holding org fixed at creation) | recreate program + opp | yes |
| OCS | **no** (manual team) | **no** (clone stays in-team) | rebuild, after D | yes, after D |
| Labs | n/a | no allowlist update | clone with new allowlist | email domain only |

## Build order

Each item is its own PR, merged when green.

1. ace-web **A**: invite-only login. On its own this lets Spark sign in to a
   workspace.
2. ace-web **B**: tenancy model, API, and the `dimagi-team` backfill.
3. ACE **D**: opp binding and the tenancy guard, with `.env` defaults retired.
4. ace-web **C**: copying a run into another workspace, and the redirect.
5. ACE **E**: command skeleton (preflight, `release` block, report), then HQ.
6. ACE **E**: Connect.
7. ACE **E**: Labs.
8. ACE **E**: OCS.
9. ACE **F**: `share-run-access`.

**First use: Spark.**

1. Create the `spark` workspace and set its default tenancy.
2. Do the manual Connect-org and OCS-team setup.
3. Run the command on `spark-facilitator/20260926-1413`.
4. Invite Anne, Sasha, Rachel and Enock.

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
  - rerun idempotence from a recorded `release` block;
  - HQ verified live on Spark first.
- **After deploy:** run `scripts/qa/labs_probe.py`.

## Out of scope

- Removing anonymous editing on the public summary (a separate, later change).
- Automating Connect org and OCS team creation, which needs upstream APIs.
- Per-user (rather than per-domain) Labs access.
- Separate ACE agents or identities per tenancy (see "One agent, and when that
  stops being enough").
- Keeping a released run in sync with later source runs. Releasing a newer run
  is another invocation.
