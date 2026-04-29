# What's new in ace-web

> If you've signed in for the first time, you no longer have to play detective to figure out how to start a chat. We tightened three concrete dead-ends along the new-user path — empty-state CTAs, an actionable inline message when Claude CLI isn't connected, and a clearer "how do I connect?" page that finally mentions the easy option.

## Highlights

- **"Start a chat" button in the empty Sessions tab** — was a one-line grey hint with no button (the *New chat* button lived only in the header, easy to miss). Now there's an explicit CTA right where you're already looking. Imported-empty also now has its own *Upload .jsonl* CTA.

  *Try it:* https://labs.connect.dimagi.com/ace/sessions when you have no sessions yet.

- **Inline "Connect Claude CLI" callout above the chat box** — the placeholder text used to read `Claude CLI not connected — visit /auth/cli to enable chat`, but the path lived inside a textarea so you couldn't click it. Replaced with a real amber callout sitting directly above the input, with a clickable **Connect now →** link.

  *Try it:* https://labs.connect.dimagi.com/ace/chat in a session where the server doesn't have CLI credentials yet.

- **Connect Claude CLI page now leads with the easy path** — used to push the python-script flow first, which assumes you have the repo checked out and python ready. Now leads with `/ace-web:create-cli-credentials` (a Claude Code slash command, one line) and keeps the script as the fallback for users without Claude Code. The disconnected-state copy stops being operator-speak and starts being user-friendly.

  *Try it:* https://labs.connect.dimagi.com/ace/auth/cli

---

## * Internal notes

**Sprint summary:** first-chat-path, 1 PR (bundled), one autonomous cycle, ~45 min wall-clock (most of it spent on tooling bootstrap in a fresh worktree — `.venv` and `node_modules` had to be built from scratch).

**What shipped (engineering view):**

| PR  | Lens          | Title                                          | Self-review verdict   |
|-----|---------------|------------------------------------------------|-----------------------|
| #143 | adoption / UX | clearer first-chat path for new web-only users | "would defend in CR"  |

**Self-review blocks (proposals dropped before PR):**
- None this sprint.

**Deploy / health:**
- 1 deploy, green. https://labs.connect.dimagi.com/ace/api/health returned 200 immediately on the first poll.

**Convince-self gate verdicts:**
- 3a (mechanical): tsc -b clean, ruff clean, 519/519 pytest pass, secret scan clean, diff size 233/1500 lines. PASS.
- 3b (5 questions): all answered in run log; the riskiest line is `SendBox.tsx`'s direct `react-router-dom` import (consistent with existing `CliAuthBanner` precedent); no test patched to match changed behavior. PASS.
- 3c (dogfood): SKIPPED per project learning ("pure UI/copy changes ship with `tsc -b` + a written manual test plan as the verification ceiling — don't block on 'exercise the live flow' when it requires a fresh user + real third-party state to set up"). Manual test plan in PR body.
- 3d (post-deploy): PASS on first poll.

**What I'd do next** (suggestion, not commitment):
- The two carryover items from the trust-reliability cycle (apps/opps/seed.py exception leak; apps/sessions/auto_title.py logger.warning → exception) are still in backlog and would make a clean tech-debt cycle.
- The "Linked chats panel preview snippet" item from integration-depth is still in backlog.
- A pure tech-debt cycle (the next lens in rotation) could revisit the legacy `google_sub` no-op field, which CLAUDE.md notes is "kept to avoid a schema migration."

---

## ** Canopy self-improvement notes

No new universal lessons this sprint. The two candidates I'm watching but holding back on a canopy PR for:

- **"Worktree environments often lack tooling — bootstrap defensively."** This cycle and the prior adoption-blockers cycle both hit a missing `.venv` / missing `node_modules` setup tax in fresh emdash worktrees. The autonomous mechanical-checks gate assumes tooling exists. Single confirming case isn't quite enough for a universal lesson; one more would make it.
- **"Stale assumption docstrings outlive the assumption."** Already captured in the project's own `learnings.md` — needs a third confirming case before promoting universal.
