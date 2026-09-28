# Invite-only login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** building (2026-09-28)

**Goal:** Let people outside `ACE_ALLOWED_EMAIL_DOMAINS` sign in when they
have a pending workspace invite or an existing workspace membership.

**Architecture:** Move the domain check out of `oauth_callback` into a pure
function `apps/auth/login_gate.py::admission_rule(email) -> str | None`. It
returns the rule that admitted the email (`"domain"`, `"invite"`,
`"membership"`, `"open"`), or `None` to reject. `oauth_callback` calls it
before creating the User row, and logs the rule for non-domain admissions.
The invite page gets a line telling partners to sign in with CommCare HQ
first.

**Tech Stack:** Django 5, pytest-django (in-memory SQLite), React/vitest for
the invite page copy.

**Spec:** `docs/specs/2026-09-28-clone-and-release-design.md` § A

## Global Constraints

- An empty `ACE_ALLOWED_EMAIL_DOMAINS` still admits everyone. Its behaviour is
  unchanged.
- Email comparison is lower-cased.
- A rejected sign-in creates no User row.
- The rejection message keeps "Access is restricted to …" and adds "If you
  were invited, sign in with the email address the invite was sent to."

## Review Focus

1. **Accepted invite, no membership left:** someone who accepted an invite and
   was later removed from every workspace is rejected. Tested in Task 1.
2. **Mixed-case invite email:** an invite stored as `Anne@Spark.org` must
   admit `anne@spark.org`. Tested in Task 1.
3. **Revoked or expired invite:** these do not admit. Tested in Task 1.
4. **Membership but no User row:** impossible, because memberships FK to User;
   the membership query goes through `user__email__iexact`. Tested in Task 1.
5. **Empty email from Connect:** rejected when a domain list is set, and never
   matched against invites. Tested in Task 1.

---

### Task 1: `admission_rule` with tests

**Files:**
- Create: `apps/auth/login_gate.py`
- Test: `apps/auth/tests/test_login_gate.py`

**Interfaces:**
- Produces: `admission_rule(email: str) -> str | None`

Tests cover:

- **Admitted:**
  - by domain;
  - by an open (empty) domain list;
  - by a pending invite, with mixed case;
  - by membership.
- **Rejected:**
  - an expired invite;
  - a revoked invite;
  - an accepted invite with no membership;
  - no invite;
  - an empty email.

Run: `.venv/bin/pytest apps/auth/tests/test_login_gate.py -v`

### Task 2: Wire it into `oauth_callback`

**Files:**
- Modify: `apps/auth/oauth_views.py` (the domain-gate block)
- Test: `apps/auth/tests/test_oauth_callback_gate.py`

The test drives `oauth_callback` with the token exchange, introspection and
userinfo mocked:

- An invited outsider gets logged in, and a User row is created.
- A stranger is redirected to login with the message, and no User row is
  created.

### Task 3: Invite page copy

**Files:**
- Modify: `frontend/src/pages/InviteAcceptPage.tsx`

It adds one line under the sign-in button: "Use **Log in with CommCare HQ** on
the Connect page, and sign in with the email address this invite was sent to."

### Task 4: Docs + ship

- Update the Auth bullet in `CLAUDE.md` to say sign-in is admitted by domain,
  a pending invite, or an existing membership.
- Run the full `pytest`, `ruff`, `bunx tsc -b` and `bun run test`, then open
  the PR and merge when green.
