# ace-web — Product Context

## What It Is
A browser-based chat + opportunity Workbench harness for the ACE (CRISPR-Connect) initiative — talks to Claude via local CLI (subscription auth), reads/writes a shared Google Drive folder where ACE opportunities live, and visualizes per-skill artifacts, gates, and scorecards.

## Who Uses It
- **Primary users today**: the Dimagi ACE team (`@dimagi.com` users) running CRISPR-Connect cycles via the `ace` plugin in Claude CLI, then inspecting/discussing the resulting Drive artifacts in the browser.
- **Aspirational users (the lens for this scout)**: third-party / web-only users who never touch the CLI plugin — they log in, share a Google Drive folder with the service account, and "say go." Today this path is broken/undocumented.
- **Usage pattern**: improvement loop — run → inspect Workbench → discuss in chat → upgrade plugin/skill → rerun (overwriting) → compare via tags.

## What Matters Most
1. **Make the web-only third-party user path real** — today the Drive root folder is a single hard-coded id (`ACE_DRIVE_ROOT_FOLDER_ID`), there's no onboarding, and the README/UI copy assume the user is already inside the ACE plugin world.
2. **Right and elegant over speed** — craftsmanship on what's already in scope; not "ship MVP first / polish later."
3. **Don't add Phase 5 polish work proactively** — initial dev is officially complete; only address concrete pain points.

## Tech Stack
- Django 5 + Channels 4 + DRF (ASGI/uvicorn), React 19 + Vite + Tailwind 3.4 + shadcn/ui
- Postgres (RDS in prod), AWS ECS Fargate behind connect-labs ALB at `/ace/*`
- Google Drive via shared service account (`ace-drive` in `apps/service_accounts/registry`); supports per-user impersonation via `ImpersonationGrant`
- Claude CLI subprocess (`apps/common/CLIBackend`) using a global subscription credential blob in `SystemConfig` (per-user creds are future work)
- Vendored `ace` plugin at `/app/vendor/ace` for skill metadata + slash commands

## Current State
- Phases 1–4 shipped; Phase 5 (Polish) deferred indefinitely
- Web-native opp creation exists (`apps/opps/opp_creator.py` + `NewOppDialog`) but the `OppListPage` empty state still says "Run ACE against an opportunity and it will show up here" — a stale instruction
- `apps/service_accounts/` has full credential registry + impersonation + audit log infrastructure, but no per-user/per-tenant Drive root folder concept yet — every user reads from the same hard-coded `ACE_DRIVE_ROOT_FOLDER_ID`
- README.md is 47 lines and says "Plan 1A complete" — useless to a new arrival

## Known Considerations
- Drive is the source of truth — don't propose Postgres mirrors of opp content
- Visualization view is refresh-to-update, not live-pushed
- Plugin-driven dynamic skill registry — adding a skill is a one-file edit in `../ace`, not in this repo
- `@dimagi.com` email filter is enforced at OAuth callback today; opening to third parties needs a deliberate policy choice, not just a code change
- Per-user CLI credentials are explicitly future work (`docs/plans/2026-04-18-per-user-cli-credentials.md`) — relevant to "web-only user runs their own Claude" story
- The team uses tags (free-form) on `OppWorkspace` to group sibling opps; multi-run was deliberately removed
