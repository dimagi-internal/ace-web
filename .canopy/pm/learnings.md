# Product Management Learnings

Items closed or rejected during PM cycles. Read this before every scout run to avoid re-proposing.

## Closed Items
- **Global keyboard navigation across viewer surfaces** (`j/k`, `/`, `?`, `g o`/`g s`). Closed 2026-05-13-viewer-defaults. Reason: "too speculative — needs a clearer pain point." For solo view-mode workflows, don't propose generic keyboard nav unless the user surfaces a concrete moment-by-moment friction that keyboard nav specifically would close. The mouse-click count alone is not enough signal.

## Preferences
- **PhaseView is the workhorse UI for opp interactions, not OppWorkbench.** When proposing new actions / affordances on opps (push buttons, integration hooks, etc.), default to PhaseView placement, not the Workbench header. The Workbench is the framing container; phases are where the user actually works. Surfaced 2026-05-24-slack-discoverability — proposal to put a "Mirror in Slack" chip on the Workbench header was redirected explicitly to PhaseView.
- **Real lens for ace-web today is solo view-mode use, not third-party adoption.** (Override of the prior 2026-04-27 default.) The sole user prefers the CLI for running and uses ace-web mostly to view what another agent's runs produce. Scout lenses should target view-experience friction (legibility, scan-ability, default landings) until that changes.
- Lens to default to when user doesn't specify: solo view-mode (per 2026-05-13 scout request)
- "Right and elegant over speed" — bias toward the thorough option, not MVP/polish split
- Phase 5 polish work (observability, evals, a11y, security review) is deferred — do not propose unless a concrete pain point surfaces
- For first-impression / new-user-polish slices, bundle related items into ONE PR rather than splitting per-finding — coherent story, less review overhead (validated 2026-04-28-user-value)
- Pure UI/copy changes can ship with `tsc -b` + a written manual test plan as the verification ceiling — don't block on "exercise the live flow" when it requires a fresh user + real third-party state to set up
- For "is X discoverable from the web?" scouts, one cross-grep against the user-visible surface tree (`grep -ri "<feature>" frontend/src/`) is the single most decisive diagnostic — converts vague hunches into hard observations faster than reading any individual file. Validated 2026-05-24-slack-discoverability: confirmed Slack was invisible in one shell command.

## Pending context refresh
(none — context.md refreshed 2026-04-28 before the adoption-blockers cycle)

## Anti-patterns observed
- **Pin-the-literal tests codify drift.** `apps/opps/tests/test_resolve_root_folder.py::test_default_setting_is_the_shared_ace_folder_id` claimed to be a "fail loudly on accidental edit" guard, but actually pinned the leaked literal value into the test suite — meaning the architecturally correct fix (default empty post-Workspaces) tripped the guard. Prefer asserting the *invariant* ("default is empty / not tenant-specific") over the literal value. Surfaced 2026-04-28-adoption-blockers.
- **Tests that codify bug-as-feature recur.** When a test docstring describes a behavior that's objectionable under the current security model (e.g. "any authed user can read any session across tenants"), it's almost always pinning a deferred-work assumption that's now stale. Two examples from 2026-04-28: `test_connect_auto_joins_non_participant` and `test_messages_list_allows_any_authed_user`, both written when `@dimagi.com` was the only auth path AND there was no multi-tenancy. Treat as code-smell during scout; the docstring tells you what's wrong.
- **Stale "for now / deferred / temporary" docstrings outlive the assumption that justified them.** When a foundational assumption changes (dropping the `@dimagi.com` filter, adding multi-tenancy, opening to third parties), grep for "for now", "deferred", "temporary", "future sharing", "Dimagi user" in apps/. Each hit is a candidate for the assumption-was-supposed-to-protect-this kind of bug. Surfaced 2026-04-28-trust-reliability — the cross-workspace session leak was right there in the docstring.
