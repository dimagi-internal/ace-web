# Normal login for ace-web — email + password, Google, CommCare

Date: 2026-10-08. Owner request (Jonathan): "I didn't realize ace-web required
commcarehq logins, that's not going to work, lets build a normal login system as
well for ace-web (using normal django best practices) but then also have login
with commcare or login with google options."

## Problem

The only way into ace-web was Connect OAuth → CommCare HQ. Partners with no HQ
account could not get in, and fleet agents (hal@, ada@ dimagi-ai.com) needed an
HQ account just to obtain an ace-web token.

## Design

Three ways in, one gate behind them.

```
 password ──┐                       ┌─ admit()        login_gate.admission_rule
 Google  ───┼─► prove who you are ─►├─ resolve_user() link by email (iexact)
 CommCare ──┘   (per method)        └─ start_session() login() + auto-join
                                         apps/auth/identity.py
```

* `apps/auth/identity.py` is the single module. A method only supplies its proof
  of identity; admission, account linking, session rotation and auto-join are
  shared. `apps/auth/tests/test_admission_parity.py` runs every admission rule through all
  three real views.
* **Password:** Django's own `LoginView`, `PasswordResetView`/`ConfirmView`,
  `PasswordChangeView`; stock validators (min length 12); Argon2 first, PBKDF2
  kept so existing hashes verify and upgrade on next login. Login name is the
  email, matched case-insensitively (`UserManager.get_by_natural_key`).
* **Google:** hand-rolled OIDC authorization code + PKCE (`google_oauth.py`,
  `google_views.py`), the same shape as the Connect flow, using httpx and the
  PyJWT already in the tree. authlib was not adopted: one more dependency for
  ~100 lines, and ace-web already hand-rolls Connect; django-allauth stays out
  (CLAUDE.md). Checked: `state`, PKCE S256, RS256 signature against Google's
  JWKS, `iss`, `aud`, `exp`, `nonce`, and `email_verified` (required).
* **CommCare:** the existing Connect flow, unchanged except that its tail now
  calls `identity.sign_in`.

### No open signup

A password is set only by (a) accepting a `WorkspaceInvite` on the public invite
page (`/auth/invite/<token>/`: set a password, Google, or CommCare), or (b) a
Django admin creating the user. `/invite/<token>` sends anonymous visitors to
that page; signed-in visitors get the SPA accept page as before.

**An invite link can create a password account but can never set a password on
an account that already exists** — otherwise whoever holds the link could take
over a user who came in through Connect or Google. Existing users sign in the
way they did before, then add a password at `/auth/password/`.

### Linking

One `User` per person, matched by email case-insensitively. Connect-first users
add a password (`/auth/password/`, no old password needed while none is set) or
Google (`/auth/google/initiate/?mode=link`) from `/auth/account/`. A Google
identity attaches only when its email is verified AND equals the account's
email; a Google `sub` already on another user, or a different `sub` already on
this user, is refused (never silently replaced).

### Brute force

`apps/common/rate_limit.py` (cache fixed window, fails open) on the login and
reset endpoints, per client address AND per target email, so rotating
`X-Forwarded-For` does not unlock one account. Defaults in `settings/base.py`
(`ACE_LOGIN_RATE_LIMIT_*`, `ACE_RESET_RATE_LIMIT_*`). django-axes was not
adopted: no new dependency or model, and the project already owns this limiter.
Trade-off: an attacker can burn a victim's per-email budget for the window
(15 min, 10 attempts) — a lockout, not a breach.

### Password reset

Behind `ACE_PASSWORD_RESET_ENABLED` (default **off**). ace-web has no outbound
email in prod, and a reset form whose mail goes nowhere is worse than none: the
routes 404 and the "Forgot your password?" link is hidden until the flag is on.
Responses are identical whether or not the address has an account (accounts with
no password, deactivated accounts and no-longer-admitted accounts get no mail,
silently), and rate-limit hits answer exactly like a send. Links last one hour.

### Unchanged

Session cookies (`sessionid_ace`, `csrftoken_ace`, path `/ace/`); the
`PersonalToken` model and `BearerTokenAuthMiddleware`; `/auth/cli/authorize/`
(`@login_required`, so a password session now authorizes a CLI token — tested).

### Behaviour changes worth knowing

* A deactivated user (`is_active=False`) is now refused by every method;
  `login()` alone does not check it and the Connect path used to let them in.
* `/admin/login/` redirects to the one login page, so the admin is not a fourth
  door around the gate. A staff account must therefore itself be admitted.
* An unconfigured Connect `initiate` redirects to the login page with a message
  instead of returning a bare 500.
