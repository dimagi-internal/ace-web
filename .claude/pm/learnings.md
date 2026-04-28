# Product Management Learnings

Items closed or rejected during PM cycles. Read this before every scout run to avoid re-proposing.

## Closed Items
(none yet)

## Preferences
- Lens to default to when user doesn't specify: web-only / third-party adoption (per 2026-04-27 scout request)
- "Right and elegant over speed" — bias toward the thorough option, not MVP/polish split
- Phase 5 polish work (observability, evals, a11y, security review) is deferred — do not propose unless a concrete pain point surfaces
- For first-impression / new-user-polish slices, bundle related items into ONE PR rather than splitting per-finding — coherent story, less review overhead (validated 2026-04-28-user-value)
- Pure UI/copy changes can ship with `tsc -b` + a written manual test plan as the verification ceiling — don't block on "exercise the live flow" when it requires a fresh user + real third-party state to set up

## Pending context refresh
(none — context.md refreshed 2026-04-28 before the adoption-blockers cycle)

## Anti-patterns observed
- **Pin-the-literal tests codify drift.** `apps/opps/tests/test_resolve_root_folder.py::test_default_setting_is_the_shared_ace_folder_id` claimed to be a "fail loudly on accidental edit" guard, but actually pinned the leaked literal value into the test suite — meaning the architecturally correct fix (default empty post-Workspaces) tripped the guard. Prefer asserting the *invariant* ("default is empty / not tenant-specific") over the literal value. Surfaced 2026-04-28-adoption-blockers.
