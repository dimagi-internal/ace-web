# Recreate a run for an external partner

**Date**: 2026-09-28
**Status**: Approved in conversation (Jonathan, 2026-09-28), spec under review
**Owner**: Jonathan Jackson
**Working name**: `recreate-for-partner` (placeholder; a better name will come later)
**Spans**: ace-web (this repo) and the ACE plugin (`dimagi-internal/ace`)
**Background**: ACE's design doc "External reviewer access to ACE runs — design v1"
(Google Doc `1DMFXXUikPo_e-UU3zT7Zq8CQ6OMFPKKtna00VWGLmio`, written in the
ACE turn on the "Connect + Spark" thread, 2026-09-28)

## Why

Spark Microgrants were the first external team to review an ACE run
(`spark-facilitator/20260926-1413`). What they could and could not open showed
that ACE's access model only works for Dimagi staff:

1. **They cannot sign in to ace-web.** The only sign-in is Connect OAuth, and
   production rejects any email outside `ACE_ALLOWED_EMAIL_DOMAINS`
   (dimagi.com, dimagi-ai.com, dimagi-associate.com) before an account exists
   (`apps/auth/oauth_views.py`). An invite to a Spark address can never be
   accepted.
2. **Each access grant we use today exposes every ACE run.** While building,
   ACE puts everything in shared tenants: one HQ project space
   (`connect-ace-prod`), one Connect network-manager org, one OCS team, and
   Labs synthetic opps limited to Dimagi domains. HQ App Editor, Connect org
   viewer and OCS Chatbot Admin each open every opp in that tenant, not just
   the partner's.

Building in shared tenants is right while ACE iterates. When a run is ready for
a real external review, its assets should move into areas that belong to the
partner, so the partner can be given access that shows only their own things.
**The end state is what the partner would have if they had built and
configured everything themselves, instead of ACE.**

## Decisions (Jonathan, 2026-09-28)

- ace-web gets **invite-only login** for people outside the domain list, rather
  than adding each partner's domain to it.
- Partners get **their own HQ project space and their own Connect orgs** (and
  their own OCS team and Labs scope).
- Anonymous editing on the public summary is **out of scope**. It will be
  removed entirely once this system is in place.
- This is **its own command, run on a completed run**, not a mode of `/ace:run`,
  and not a switch to build in partner tenants from the start.
- ACE commits and merges its own PRs as the work iterates.

## Shape

Nothing outside Drive can actually be *moved* (see "What each system can do"),
so the command **recreates** the run's assets in the partner's areas. The
source run is untouched and stays ACE's internal record.

```
/ace:recreate-for-partner <opp>/<run-id> --partner <workspace-slug>
```

Four stages, in order:

1. **Preflight.** Read the partner profile (below) and check every one-time
   setup item in each system. If anything is missing, stop **before creating
   anything** and list exactly what a human has to do, e.g. "Connect staff:
   create a program-manager org `spark` and add ace@dimagi-ai.com as admin".
2. **Recreate.** One step per system: ace-web, HQ, Connect, Labs, OCS. Each
   step records what it created in a `promotion` block, both in the new run's
   `run_state.yaml` and in the source run's, which points forward.
3. **Invite.** Invite each reviewer in the profile to each system with a role
   limited to the partner's area. Like `share-run-access`, every invite is
   shown for approval before it is sent.
4. **Report.** Per system: created, invited, or NOT DONE with the reason, each
   with a read-back proving it (the id, the URL, the member list).

**Resumable and idempotent.** A step whose `promotion` entry is complete is
skipped on rerun. A step that may have succeeded without confirming it (the HQ
app copy often times out after the copy is made) re-lists before retrying,
because a blind retry makes a duplicate.

## Partner profile (ace-web)

A partner **is** an ace-web workspace (e.g. `spark`). The `Workspace` row gets a
`partner_profile` JSON field:

```yaml
hq_domain: connect-ace-spark        # HQ project space for this partner
connect_pm_org: spark-pm            # Connect program-manager org (ACE is admin)
connect_holding_org: spark          # Connect org that holds the opportunity
ocs_team: spark                     # OCS team slug
labs_allowed_domains: ["@sparkmicrogrants.org"]
reviewers:
  - {email: anne@sparkmicrogrants.org, role: viewer}
```

- Owners edit it on the Workspace Settings page and through
  `PATCH /api/workspaces/{slug}`, the same path as `auto_join_domains`.
- ACE reads it through ace-web's API (PAT auth). There is one place to look,
  and it sits next to the member list it describes.
- Every field is optional. The preflight reports a missing field as a missing
  setup item, rather than guessing a name.

## ace-web changes

### A. Invite-only login

The domain gate in `oauth_callback` lets a sign-in through when **any** of these
is true:

- the email's domain is in `ACE_ALLOWED_EMAIL_DOMAINS` (unchanged);
- the email has a **pending** `WorkspaceInvite` (not accepted, revoked or
  expired);
- the email already belongs to a user with **at least one**
  `WorkspaceMembership`.

The third condition is required: accepting an invite marks it used, so without
it a partner could sign in once and never again. Removing someone's last
membership therefore also removes their ability to sign in, which is the right
way to cut off a partner.

- Emails are compared lower-cased, matching how invites are stored and
  accepted.
- A rejected sign-in keeps today's message and adds: "If you were invited, sign
  in with the email address the invite was sent to."
- The User row is still created only **after** the gate passes, so a rejected
  outsider leaves nothing behind.
- Audit: a sign-in admitted by an invite or a membership (not a domain) logs
  which rule admitted it.

The flow for a partner: the owner invites the partner's HQ email → the partner
opens `/invite/<token>` → "Log in with CommCare HQ" at Connect (which creates
their Connect identity in one step) → back in ace-web → accept.

**Connect SSO trap, for the invite email copy:** someone who accepts a
*Connect* invite before ever signing in with HQ gets a Connect password account,
and HQ sign-in then fails for them. The ace-web invite page tells partners to
use "Log in with CommCare HQ" first.

### B. Copying a run into another workspace

- **Endpoint:** a new owner-only endpoint copies a run into another workspace
  where the caller is also an owner. It is **not** a fork: it copies the run
  whole, with every phase and every product. It reuses the Drive copy machinery
  in `opp_forker.py` (write `run_state.yaml` first, bulk copy, 429-only retry,
  progress polling).
- **Where the copy lands:** under the target workspace's `drive_root_folder_id`,
  as `<opp-slug>/runs/<run-id>/`, with the same run id. An `OppWorkspace` row is
  created in the target workspace if the opp doesn't have one there yet.
- **Rewriting products:** the copied `run_state.yaml` then has its
  `products` blocks rewritten by the ACE command as each system is recreated.
  Until then, it still points at the shared-tenant assets.
- **Redirect:** the source run records `promoted_to: {workspace, opp, run}`.
  The public summary endpoint for the source run redirects (HTTP 308) to the
  promoted run's summary once the promotion's ace-web step is complete. The
  link Spark already has therefore lands on the partner's copy. The Workbench
  shows internal users a banner linking to the partner copy instead of
  redirecting them.
- **Cache:** the snapshot cache for both runs is invalidated. `_KEY_VERSION` is
  unchanged, because `promoted_to` is an optional field the loader passes
  through.

### C. Partner profile field

This is a migration adding `Workspace.partner_profile` (JSONField, default
`{}`), with Pydantic validation on write, the API field, and a Settings panel.

## ACE changes (`dimagi-internal/ace`)

A new command `commands/recreate-for-partner.md` and skill
`skills/recreate-for-partner/`, with one sub-step per system. Each ships on its
own, in this order.

### HQ

- Create `hq_domain` if it does not exist (`commcare_create_domain`). ACE owns
  it; the partner is invited.
- Copy the Learn and Deliver apps with `commcare_linked_app_copy(linked:false)`.
  This is an unlinked copy, so no Pro Edition is needed. The copy keeps the
  camera-only and grid-menu settings.
- Build and release them (`commcare_make_build`, `commcare_release_build`),
  recording `hq_app_id`s.
- Invite reviewers with `commcare_invite_web_user`. App Editor is acceptable
  here, because the space contains only this partner's apps.
- **Not in v1:** mobile workers. ACE has no tool to create them. The report
  lists this as a manual step (or Nova's `upload_to_hq` persona workers).
- The cross-space unlinked copy has only been tested live within one space. The
  first real run must verify it on Spark before any other system is built on it.

### Connect

- **Preflight requires** `connect_pm_org` and `connect_holding_org` to exist
  with ACE as admin, and the holding org to have an accepted program
  application. There is no tool to create an org, so Connect staff do this by
  hand once per partner.
- Recreate the program in `connect_pm_org` and the opportunity targeting
  `connect_holding_org`. They point at the **new** HQ apps, with the payment
  units, verification flags and dates read from the source run's `connect`
  products.
- Invite reviewers with `connect_add_org_member`, as viewer by default, into
  the partner's orgs only.

### Labs

- Clone each synthetic opp in `synthetic.cascade` with
  `allowed_domains = labs_allowed_domains`. There is no tool to update the
  allowlist on an existing opp, so they are cloned.
- Copy the run's workflows and dashboards (`copy_workflow`) onto the clones,
  and rewrite `synthetic.*` in the new run.
- The finest access control available is an email domain, not a single user.
  That is acceptable because the opp is the partner's own.

### OCS

- **Preflight requires** an OCS team `ocs_team` and ACE credentials for it: a
  login plus `OCS_API_TOKEN_<SLUG>`. There is no tool to create a team.
- The write tools (`ocs_create_chatbot`, collection upload, prompt, publish,
  `ocs_add_team_member`) gain a `team_slug` argument. Today they only reach
  `OCS_TEAM_SLUG`.
- The bot is **rebuilt** in the partner team: same prompt, knowledge files and
  settings from the source run's `ocs_chatbot` products. Cloning cannot cross
  teams.
- OCS is last because it is the only system that needs tool changes first.

### share-run-access

It stays as the internal-reviewer path. Two changes:

- Fix ace#2525.
- Refuse the whole-tenant grants (HQ App Editor on `connect-ace-prod`, Connect
  NM-org viewer, OCS Chatbot Admin) for non-Dimagi addresses, pointing at
  `recreate-for-partner` instead.

## What each system can do (research, 2026-09-28)

| System | Create a partner area | Move assets | Copy / recreate | Scoped invite |
|---|---|---|---|---|
| ace-web | yes (workspace) | yes, Drive | yes | yes, after (A) |
| HQ | yes, `commcare_create_domain` | no | app copy across spaces | yes |
| Connect | **no** (manual org) | **no** (holding org fixed at creation) | recreate program + opp | yes |
| OCS | **no** (manual team) | **no** (clone stays in-team) | rebuild, after tool change | yes, after tool change |
| Labs | n/a | no allowlist update | clone with new allowlist | email domain only |

## Build order

Each item is its own PR, and each merges when green.

1. ace-web **A** — invite-only login. On its own this lets Spark sign in to a
   workspace.
2. ace-web **C** — the partner profile field and Settings panel.
3. ace-web **B** — copying a run into another workspace, plus the summary
   redirect.
4. ACE — the command skeleton: preflight, `promotion` block, report. Then HQ.
5. ACE — Connect.
6. ACE — Labs.
7. ACE — the OCS tool changes, then OCS.
8. ACE — the `share-run-access` changes.

**First use:** Spark. Create the `spark` workspace, fill in its profile, do the
manual Connect org and OCS team setup, run the command on
`spark-facilitator/20260926-1413`, and invite Anne, Sasha, Rachel and Enock.

## Testing

- **A:** unit tests on the gate in `apps/auth/test_login_views.py`:
  - admitted by domain;
  - admitted by a pending invite (case-insensitive);
  - admitted by an existing membership;
  - rejected when the invite is expired, revoked or accepted and the user has
    no membership;
  - rejected with no invite, and no User row created;
  - admitted by domain when the domain list is empty (unchanged).
- **B:**
  - The copy endpoint, with the Drive client faked the way `opp_forker` tests
    do.
  - The redirect only appears once `promoted_to` is set and the step is
    complete.
  - A non-owner of either workspace gets 404.
- **C:** schema validation and an owner-only PATCH.
- **ACE:**
  - Each step has a dry-run mode that prints the calls it would make.
  - Rerun idempotence is tested with a recorded `promotion` block.
  - The HQ copy step is verified live on Spark first.
- **After deploy:** `scripts/qa/labs_probe.py`.

## Out of scope

- Removing anonymous editing on the public summary (a later change will remove
  it entirely).
- Automating Connect org and OCS team creation. These need upstream APIs.
- Per-user (rather than per-domain) Labs access.
- Keeping a promoted run in sync with later source runs. Promoting a newer run
  is another invocation of the command.
