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
- `context.md` "What Matters Most #1" still references hard-coded `ACE_DRIVE_ROOT_FOLDER_ID` — multi-tenant Workspaces shipped 2026-04-27 making that migration-only. Update before next scout to point at the real remaining third-party adoption gap (rough self-onboarding copy/error-recovery on `/welcome` + empty states that assume a Dimagi audience). Surfaced 2026-04-28-user-value.
