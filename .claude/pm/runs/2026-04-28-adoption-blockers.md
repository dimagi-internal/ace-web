## 2026-04-28 — adoption-blockers

Second cycle of the day. Lens framing: a new contributor (or curious external evaluator) running ace-web for the first time. What stops them from getting to "this works"?

Started by refreshing `context.md` since the previous cycle (2026-04-28-user-value) flagged item #1 as stale post-Workspaces.

### Do it

1. **Test-login surfaced on sign-in page when DEBUG** — Effort: S — Status: shipped
   - Branch: `ace-web/pm-scout-adoption-blockers`
   - What: `apps/auth/templates/auth/login.html` rewritten. When `DEBUG=True and ACE_ALLOW_TEST_LOGIN=True`, renders a second panel with an email input that POSTs to `/auth/test-login/` via fetch and reloads. Production DEBUG=False path unchanged. Also dropped "Dimagi" from the OAuth button copy (the `@dimagi.com` filter was removed during multi-tenancy).
   - Outcome: `apps/auth/templates/auth/login.html`, `apps/auth/oauth_views.py:31-50` (context now includes `show_test_login`, `test_login_url`, `post_login_url`).

2. **ACE_DRIVE_ROOT_FOLDER_ID stale comment + leaked default** — Effort: S — Status: shipped
   - What: default changed from the team's specific folder ID (`1HThsA_0Lr5p1OdI5r-aQ446HlNBaySLz`) to `""`. Comment rewritten to "migration-only — only read by apps/workspaces/migrations/0002_seed_dimagi_team.py to seed the founding workspace; not read at runtime." Updated `apps/opps/tests/test_resolve_root_folder.py::test_default_setting_is_empty_string` to assert the new contract.
   - Outcome: `config/settings/base.py:151-160`, test name + body refreshed.

3. **README + .env.example: no-credentials onboarding** — Effort: S — Status: shipped
   - What: README "Quick start" section now includes a "Trying it out — no credentials needed" walkthrough showing the test-login path, the FakeCLIBackend default, and the path to wiring up real ACE. `.env.example` gains an informational comment block listing all dev-only escape hatches and optional knobs (ACE_ALLOW_TEST_LOGIN, ACE_USE_FAKE_CLI_BACKEND, ACE_DRIVE_SA_KEY_JSON, ANTHROPIC_API_KEY, ACE_ALLOWED_EMAIL_DOMAINS, ACE_E2E_AUTH_TOKEN) with one-liners.
   - Outcome: `README.md` Quick start section, `.env.example` doubled in size (purely docs).

### Backlog
(none)

### Closed
(none)

### Meta-observations

- **Inverse sweep on `.env.example` was clean (no dead ceremony).** All 4 keys in the template are read. The interesting case was the *forward* drift: vars the code reads that the template doesn't acknowledge — but most weren't classic adoption blockers (DATABASE_URL, REDIS_URL etc. are wired up by docker-compose). The real find was that `ACE_ALLOW_TEST_LOGIN` and `ACE_USE_FAKE_CLI_BACKEND` are *already on* in dev — but the *escape hatch they unlock* (test-login UI) was invisible. So the fix wasn't "add to template" but "expose in the UI" + "tell people about it."
- **The 'pinned literal so an accidental edit fails loudly' test** (`test_default_setting_is_the_shared_ace_folder_id`) ironically codified the leak — it was guarding the wrong invariant. Worth noticing that pin-the-current-value tests can become stale when the surrounding architecture moves out from under them. Lesson: pin invariants ("default is empty / safe / non-revealing"), not literals.
- **One bundled PR again** — three thematically-coherent items, single PR. Pattern continues to work for these polish slices. Not a new lesson, just confirmation.
- **Context refresh first.** Spent ~2 min refreshing `context.md` before scouting; the scout was sharper because the framing was current. Worth doing whenever a previous run flagged the context as stale.
- **uv setup gotcha for local pytest:** `uv sync --frozen` doesn't install dev deps that aren't in the project's resolved lock. Had to `uv pip install pytest pytest-django pytest-asyncio fakeredis ruff` directly into `.venv/`. Possibly a `pyproject.toml` `[dependency-groups]` issue or an artifact of running outside docker. Not actionable here, but worth flagging if it recurs across worktrees.

### Universal-improvement candidates

- **"Pin invariants, not literals"** — could be a universal lesson. But single observation; needs more evidence before opening a canopy PR. Holding for now.
- **The `tsc -b` + manual-test-plan ceiling** observation from the prior cycle still applies (the login.html change has the same shape: I can't easily exercise the real "fresh dev hits OAuth wall" experience in a unit test). Still single-cycle scope; still holding.
