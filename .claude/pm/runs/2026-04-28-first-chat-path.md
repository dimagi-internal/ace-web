## 2026-04-28 — first-chat-path (autonomous)

Fifth cycle of the day, first autonomous run. Lens framing: third-party / web-only user
who has just completed the welcome flow, hits `/sessions` or clicks into chat, and
discovers (the hard way) that "first chat" isn't a one-click experience.

### Phase A — target email DRAFT (pre-implementation)

```markdown
# What's new in ace-web

> If you've just signed in for the first time, you no longer have to play detective to
> figure out how to start a chat. We tightened three gaps along the new-user path —
> empty-state CTAs, an actionable inline message when Claude CLI isn't connected, and
> a clearer "how do I connect?" page that finally mentions the easy option.

## Highlights

- **"Start a chat" button in the empty Sessions tab** — was a one-line grey hint with
  no button. Now a real CTA that opens a new chat in one click.
  *Try it:* https://labs.connect.dimagi.com/ace/sessions when you have no sessions yet.

- **Inline "Connect Claude CLI" callout in the chat box** — the placeholder used to read
  `Claude CLI not connected — visit /auth/cli to enable chat`, but the path was inside
  a textarea so you couldn't click it. Replaced with a real callout above the input
  with a clickable link.
  *Try it:* https://labs.connect.dimagi.com/ace/chat in a fresh login (no CLI creds).

- **Connect Claude CLI page now leads with the easy path** — used to push the python
  script first, which assumes you have the repo checked out and python ready. Now leads
  with `/ace-web:create-cli-credentials` (Claude Code skill, one command) and keeps the
  script as the fallback.
  *Try it:* https://labs.connect.dimagi.com/ace/auth/cli

## * Internal notes

**Sprint summary:** first-chat-path, 1 PR (bundled), ~Y minutes wall-clock.

**Self-review verdict:** TBD post-gate.
```

### Self-critique on the draft

- **Clear:** PASS. Each highlight names a specific URL the reader can click. No
  placeholder language; no "improved DX" fluff.
- **Testable:** PASS. Each "Try it" line is a real assertion — open URL, observe
  specific change vs. yesterday's version. The Sessions empty state and the SendBox
  callout are visually obvious; the AuthCliPage reorder is a copy change but the
  ordering of the "How to connect" steps is the thing under test.
- **Impressive:** PASS-WITH-CAVEAT. This is polish on first-run friction, not a new
  capability. But it ties directly to context.md item #1 ("in-app guidance for the
  unfamiliar shapes... copy that doesn't assume the reader has run a CLI plugin
  before") and the persona is real. For a project in steady-state polish mode where
  each cycle has been ~3 small thematic items, this is the right shape.

Approved. Proceeding to Phase B.

### Phase B — proposals derived

Three coherent UX proposals, bundled into one PR per project preference:
1. SessionsPage empty-state CTA buttons (active-empty + imported-empty branches).
2. Inline cli-blocked callout above SendBox (replace placeholder URL).
3. AuthCliPage skill-first ordering + friendlier disconnected copy.

### Phase C — ship outcome

- Branch: `ace-web/auto/first-chat-path`
- PR: #143 — https://github.com/jjackson/ace-web/pull/143
- Convince-self gate:
  - 3a mechanical: tsc -b, ruff, 519/519 pytest, secret scan, diff size 233/1500 — all PASS
  - 3b self-review (5 questions): all PASS, see body above
  - 3c dogfood: SKIPPED per project learning ("pure UI/copy ships with manual test plan as ceiling")
  - 3d post-deploy health: PASS (200 on first poll)
- CI: pytest+ruff green in 29s
- Merged: squash into main as 17873fa
- Deploy run: 25089503751 — success in ~5min
- Health: https://labs.connect.dimagi.com/ace/api/health → 200

### Phase D — reality reconciliation

What shipped vs. drafted: all three highlights survived essentially as drafted; the
Sessions empty state ended up RICHER than drafted (also covers imported-empty with an
Upload .jsonl button), and the AuthCliPage disconnected-state copy got a friendlier
rewrite that wasn't in the draft.

Re-running Clear/Testable/Impressive: all PASS. Email proceeds to Phase E.

### Phase E — sent

- File: `.claude/pm/sent-emails/2026-04-28-first-chat-path/email.md` (markdown draft)
- Final HTML: `.claude/pm/sent-emails/2026-04-28-first-chat-path/email.html`
- Recipient: jjackson@dimagi.com
- Three sends in this cycle as quality iterated under user feedback:
  - `19dd8ac695e432ed` — markdown body (rendered as literal `##`/`**` in Gmail). ❌
  - `19dd8c230480f65d` — HTML body + `cid:` refs + `--attach` (Gmail showed broken-image placeholders, attachments-only). ❌
  - `19dd8ccb96533ed1` — HTML body + `raw.githubusercontent.com` hosted images + PM-grade design (renders correctly). ✅
- Subject (final): `[ace-web] What's new — first-chat path is no longer a maze`

### Phase E.5 — post-send self-review (added by user feedback)

Rendered the final `email.html` via `gstack load-html` at 1280×800 (desktop) and 375×812 (mobile). Saved screenshots as `email-rendered-desktop.png` / `email-rendered-mobile.png` under the screenshots dir. Critiquing as a recipient, not as the author:

**What works:**
- Brand bar reads professionally (`ACE WEB · RELEASE NOTES` with date right-aligned).
- Three highlight cards have hero screenshots that load over the wire.
- Hairline dividers between sections, restrained accent (`#4338ca` indigo) on link text.
- Footer is clearly subordinate — small grey type, divider above.

**Concrete improvements for the next cycle (top-priority first):**

1. **Make feature titles and hero images clickable** — currently each highlight has only a small "Try it on labs →" CTA at the bottom. Recipients scan. The `<h2>` and `<img>` should both wrap in `<a href="<TRY-IT-URL>">` so the natural click targets work. *Surfaced by user mid-cycle; saved as memory; needs to land in the canopy template.*
2. **Hero pitch is too long** — three sentences read like a lede paragraph. Tighten to 1-2 punchy sentences. The current paragraph buries the headline's punch.
3. **Screenshots feel pasted-in, not embedded.** They're full dark-themed app shots in a light email — the contrast jars. Two fixes: (a) crop tighter to the new feature, OR (b) wrap each in a soft frame/shadow so they read as figures, not foreign objects.
4. **The "Sessions empty-states" highlight talks about three branches but shows one screenshot.** Either show a 3-up composite of active/imported/archived empty states, or rewrite the body to focus on the single image (Archived).
5. **Replace inline `<code>` for the long placeholder string** in highlight #1 — `<code>Claude CLI not connected — visit /auth/cli to enable chat</code>` is too dense at body font size. A pull-quote treatment on its own line would land better.
6. **End with a sign-off** — current footer goes from "Up next, optionally..." straight to "Sent automatically by the autonomous PM cycle. Reply to opt out." Add a one-liner like "— ACE autonomous PM, on behalf of the Dimagi ACE team" so it doesn't feel impersonal.
7. **Mobile brand bar text wraps** — `ACE WEB · RELEASE NOTES` wraps onto two lines at 375px. Either shorten to `ACE · RELEASE NOTES` or stack the date below explicitly with proper spacing.
8. **Reduce code formatting in the "Up next" footer** — six inline `<code>` chunks in one sentence is noise. Plain text would read better at footer scale.

**Process improvements** (i.e. things to push back into canopy, not just project memory):

- **Add Phase E.5 to `cycle.md`.** The self-review pass that produced this critique is missing from the canonical cycle. Without it, the agent claims "cycle complete" at send-and-stop, and visual quality drift (like the three iterations this cycle needed) goes unnoticed.
- **Add clickable-feature requirement to `email-format.md` reference template.** The current template's `<h2>` and `<img>` are not wrapped in anchors; the template ships the same gap I just shipped.
- **Add a "first-pass quality" step to Phase E.** Right now the cycle's only quality control is human feedback (the user pushing back through three sends). The Phase E.5 self-review should run BEFORE send, not after — but post-send self-review is a useful belt-and-suspenders backup.

These three are going into canopy PR #27 as additional commits.

### Meta-observations

- **First autonomous cycle.** Total wall-clock ~45 min — most of it spent on tooling
  bootstrap in a fresh emdash worktree (`.venv` and `node_modules` had to be built
  from scratch). The `uv sync --frozen` doesn't install dev deps; needed an explicit
  `uv pip install pytest pytest-django pytest-asyncio fakeredis ruff` afterwards.
  Same gotcha as the 2026-04-28-adoption-blockers cycle flagged. Two confirming cases
  is now enough — promoted to the universal-improvement candidates section.
- **The bundled-PR rhythm continues.** Three small thematic items, one PR. Same shape
  as cycles 1–3.
- **The autonomous gate caught nothing this sprint** — but that was expected for a
  small UI/copy diff. The convince-self gate's value will show on something with real
  risk; this cycle is a calibration point.
- **No proposals dropped** during ship. Phase A → B → C ran linearly.

### Universal-improvement candidates

- **"Worktree environments often lack tooling — autonomous mode should bootstrap
  defensively or document the assumption."** Two confirming cases now (this cycle +
  2026-04-28-adoption-blockers). The autonomous gate's mechanical-checks block
  assumes `.venv` and `node_modules` exist, but in worktree-first workflows they
  don't until first use. Options for a canopy lesson: (a) add a Phase 0 setup
  detection step, (b) document the bootstrap path in `convince-self-gate.md`, or
  (c) make `testing.unit/lint/types` config keys support a `prepare` command.
  Proposing as a canopy PR after one more confirming case across a different project.

