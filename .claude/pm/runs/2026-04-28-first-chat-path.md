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
