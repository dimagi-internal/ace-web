## 2026-05-24 — slack-discoverability

Custom lens: "ideas around making the slack integration more obvious and streamlined."
Context: branch `emdash/slack-9kjrl` is in active Slack-integration buildout (10 of the
last 16 commits touch `apps/slack/`). Architecture doc exists at
`docs/architecture/slack-integration.md`. Cross-grep `grep -ri "slack" frontend/src/`
returned essentially nothing — the integration is invisible from the web UI.

### Headline finding

Slack is undiscoverable from the web. No mention in TopNav, SettingsPage,
WorkspaceSettingsPage, WelcomePanel, HomePage, or WorkspaceActivityPage. The install
URL (`/api/slack/install`) is referenced only in an ephemeral error inside Slack
("Ask an admin to run the /api/slack/install flow") — chicken-and-egg. The orphan
test page at `/api/slack/test/` is documented in its own header as "accessed from
workspace settings or by direct URL," but workspace settings doesn't actually link
to it. All discoverability today lives *inside Slack*, behind a slash-command
mental model.

### Do it

1. **Slack section in Workspace Settings** — Effort: M — Status: pending
   - Add a Slack panel to `WorkspaceSettingsPage` showing install status (badge:
     Connected to <team> · installed by <user> · since <date>, or Not installed).
     Owners on an uninstalled workspace see an "Add to Slack" button kicking off
     `/api/slack/install`. When installed, link to `/api/slack/test/` and offer
     Reconnect/Disconnect.
   - New ninja endpoint `/api/w/<slug>/slack/status` returns
     `{installed, team_name, team_id, installed_by_email, installed_at, test_page_url}`.
   - Touches: `apps/workspaces/api.py` (or `apps/slack/api.py`),
     `apps/workspaces/schemas.py`, `frontend/src/pages/WorkspaceSettingsPage.tsx`.
   - Branch: `slack/workspace-settings-panel` (suggested)
   - Validation: owner without install clicks Add → OAuth → returns showing
     Connected. Test page link opens. Non-owners see read-only status.

2. **App Home tab for the ACE Slack bot** — Effort: M–L — Status: pending
   - Subscribe to `app_home_opened` event (currently `views.py:events` only handles
     `url_verification`). Publish a Block Kit Home view per user.
   - Content for linked users: header (`Hi @you — linked as you@dimagi.com ·
     workspace: <slug>`), "Your active tracked runs (N)" with parent-card-style
     rows + Open-in-ace-web buttons, "Workspace activity (top 5)" reusing the
     `/ace activity` row renderer, primary actions (New opp / Activity / Help).
   - Unlinked users see the Link-account CTA only.
   - Touches: `apps/slack/views.py:events`, new `apps/slack/home_view.py`,
     `apps/slack/slack_client.py` (`views.publish` helper).
   - Branch: `slack/app-home-tab` (suggested)
   - Validation: open the ACE bot's Home tab → populated state without typing.
     Trigger `/ace run` → return to Home → new row in "Your active tracked runs."
     Unit tests on the view builder; mock for `app_home_opened` payload.

### Redirected

3. **"Push this phase to Slack channel" action on PhaseView** (was: "Mirror in
   Slack" snippet on Opp Workbench) — Effort: S–M — Status: pending
   - **Original proposal**: copy-`/ace track <slug>/<run_id>` chip near the
     run-id on `OppWorkbenchPage` + an inverse "Tracked in #channel" link when a
     `SlackRunThread` exists.
   - **User redirect** (verbatim): "it makes sense to have an action but it
     should be a 'push to channel' and we can select the channels that the ACE
     slack app is in. remember that phases is our workhorse ui, not workbench."
   - **Reframed scope**: a real action button on `PhaseView` (NOT the Opp
     Workbench header) — "Push to Slack" → dropdown/picker of channels the ACE
     bot is already a member of (no command-typing, no remembering syntax). On
     submit, server-side reuses the same code path that `/ace track` calls, with
     the channel chosen by the user. Inverse signal ("Tracked in #foo") still
     useful — render it as the button's secondary state when a `SlackRunThread`
     already exists for the current run.
   - Channel picker source: Slack `conversations.list` filtered server-side to
     `is_member=True`; cache per-installation. (No new bot scope needed beyond
     existing `channels:read` / `groups:read` — confirm during implementation.)
   - Touches: new `apps/slack/api.py` endpoints
     `GET /api/w/<slug>/slack/channels` (member-only list) and
     `POST /api/w/<slug>/slack/push-phase`; new
     `frontend/src/components/views/PhasePushToSlackButton.tsx` (or wherever the
     phase action cluster lives), wired into `PhaseView`.
   - Branch: `slack/phase-push-action` (suggested)
   - Validation: open a phase in a Slack-enabled workspace → "Push to Slack"
     button present. Click → channel picker shows only channels the bot is in.
     Select a channel → message lands in that channel as a parent card +
     subsequent updates flow through the existing `SlackRunThread` mirror loop.
     When a thread already exists, the button shows "Tracked in #foo" with a
     deep link.

### Backlog
(none this cycle — user moved on after dispositioning)

### Closed
(none this cycle)

### Honorable mentions (not pitched; flagged in scout for future runs)

- Cross-promo footer on `WorkspaceActivityPage`: "Also `/ace activity` in Slack"
  with a copy-command button. Could fold into the PhaseView action above.
- `/ace help` → Block Kit with primary action buttons (currently plain mrkdwn
  wall).
- `views_auth.link_page` success page links back to ace-web (currently a flat
  "Linked!" page).
- **Third-party Slack installs blocked** — `views.py:oauth_callback` hard-codes
  `workspace = Workspace.objects.get(slug="dimagi-team")`. Real adoption blocker
  for non-Dimagi workspaces, but out of scope per the current "solo view-mode"
  preference in learnings.md.

### Meta-observations

- **PhaseView vs OppWorkbench distinction is load-bearing and not in context.md.**
  The user redirected the Workbench-header proposal explicitly because "phases is
  our workhorse ui, not workbench." That's a recurring affordance-placement rule
  that future scouts (especially for new actions on opps) should default to.
  Adding to learnings.md.
- The grep cross-check (`grep -ri "slack" frontend/src/`) returning effectively
  nothing was the single most useful diagnostic — it converted a vague hunch into
  a hard observation. Worth repeating in future "is X discoverable?" scouts: one
  cross-grep against the visible-surface tree is more decisive than reading any
  single file.
- Did NOT run the test suite or doctor this cycle — pure read-only scout. Fine
  for a scout, but the implementation cycles for #1/#2/#3 will need them.

### Skill self-improvement evaluation

Universal candidate: the "one cross-grep across the user-visible surface tree" as
a discoverability diagnostic feels generalizable beyond Slack — applies to any
integration / feature that asks "is X obvious?" Worth a learnings addition; not
clearly worth a SKILL.md edit yet (would need one more confirming case in a
different domain). Holding off on the upstream PR for now.
