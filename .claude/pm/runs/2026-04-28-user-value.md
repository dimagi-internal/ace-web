## 2026-04-28 — user-value

First PM cycle for ace-web. Lens framing: the third-party / web-only user persona that's the primary aspiration in `context.md` — someone who logs into the deployed app, has never touched the CLI plugin, and wants to "say go."

### Do it

1. **OppListPage empty state** — Effort: S — Status: shipped (PR #139)
   - Branch: `emdash/pm-scout-ygiii`
   - What: replaced `"Run ACE against an opportunity and it will show up here"` with a "Create your first opp" CTA wired to the existing `NewOppDialog`.
   - Outcome: `frontend/src/pages/OppListPage.tsx:109-128`. EmptyState still used for the filter-empty branch.

2. **NewOppDialog auto-slug** — Effort: S — Status: shipped (PR #139)
   - What: type display name → slug auto-derives via `deriveSlug()` (lowercase, hyphenate, strip invalid chars). Slug remains editable; `slugTouched` guard prevents auto-derive from clobbering user edits. Existing `SLUG_RE` validation unchanged.
   - Outcome: `frontend/src/components/opps/NewOppDialog.tsx`.

3. **WelcomePage Drive-folder polish** — Effort: M — Status: shipped (PR #139)
   - What: numbered setup steps, "how to find folder ID" inline help with URL pattern + highlighted ID, click-to-copy SA email (in both setup form and recovery panel), structured "most likely fix" checklist on verify-failed instead of a one-line nudge.
   - Outcome: `frontend/src/pages/WelcomePage.tsx`. Used existing `sonner` toast and `lucide-react` icons — no new deps.
   - Did NOT include: auto-creating the folder via API. Out of scope without a deliberate design choice (would require Drive `files.create` permission + folder-naming convention).

4. **README rewrite** — Effort: S — Status: shipped (PR #139)
   - What: was stuck at "Plan 1A complete, Plans 1B/1C/1D next." Now reflects reality (Phases 1-4 + multi-tenant Workspaces shipped, Phase 5 deferred) with outsider-friendly intro pointing at CLAUDE.md + design spec for the canonical map.
   - Outcome: `README.md` grew 47 → 100 lines.

### Backlog
(none)

### Closed
(none)

### Meta-observations

- **The bootstrap left context.md stale on item #1.** It still frames the open problem as "the Drive root is a single hard-coded `ACE_DRIVE_ROOT_FOLDER_ID`" — but multi-tenant Workspaces shipped 2026-04-27 (one day before bootstrap), and per CLAUDE.md the env var is now migration-only. The third-party adoption surface still has gaps (the four addressed in this PR), but the framing was wrong. **Action:** refresh context.md before next cycle so item #1 reflects the real remaining gap (e.g. "third-party self-onboarding works but feels rough — copy/help/error-recovery on `/welcome` and the empty states still assume a Dimagi audience").
- **Single bundled PR was right for this slice.** Four small first-impression fixes form one coherent "user lands for the first time" story; splitting would have been churn and review overhead. Aligns with the "for refactors in this area, user prefers one bundled PR over many small ones" feedback memory.
- **Worth checking the rest of the empty-state copy in a future cycle** — only checked OppListPage and SessionsPage. Other empty surfaces (Chat with no sessions, Workspace settings with no members?, Linked chats panel?) may have similar "implies CLI plugin" assumptions.
- **No code-execution validation possible** for these UI changes beyond `tsc -b` — couldn't reasonably exercise the actual `/welcome` flow without a fresh user + a real Drive folder + a real misshare. Worth flagging this as a class of work where the type-check + manual-test plan in the PR body is the verification ceiling.
- **Process worked clean** for a first cycle: read context.md + learnings.md → tour codebase by lens → 4 concrete proposals → AskUserQuestion menu → bundle into one PR. Total time end-to-end was ~30 minutes.
