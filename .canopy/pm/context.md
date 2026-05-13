# ace-web — Product Context

## What It Is
A browser-based chat + opportunity Workbench harness for the ACE (CRISPR-Connect) initiative — talks to Claude via local CLI (subscription auth), reads/writes a per-workspace Google Drive folder where ACE opportunities live, and visualizes per-skill artifacts, gates, and scorecards.

## Who Uses It
- **Primary users today**: the Dimagi ACE team (`@dimagi.com` users) running CRISPR-Connect cycles via the `ace` plugin in Claude CLI, then inspecting/discussing the resulting Drive artifacts in the browser.
- **Aspirational users (the lens for this scout)**: third-party / web-only users who never touch the CLI plugin — they log in, create a workspace, share a Google Drive folder with the service account, and run opps in-browser.
- **Usage pattern**: improvement loop — run → inspect Workbench → discuss in chat → upgrade plugin/skill → rerun (overwriting) → compare via tags.

## What Matters Most
1. **Make the web-only third-party user path real** — multi-tenant Workspaces shipped 2026-04-27 (each workspace owns its own Drive folder + member list) and the first-impression polish landed in PR #139 (welcome flow, empty states, README). Remaining gaps are about *trust* and *productive use* once a third-party is in: in-app guidance for the unfamiliar Workbench shapes, error recovery when an ACE run partially fails, and copy that doesn't assume the reader has run a CLI plugin before.
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
- Multi-tenant Workspaces shipped 2026-04-27 (Owner / Editor / Viewer roles, self-onboarding at `/welcome`, invite-by-email at `/invite/<token>`); the legacy `ACE_DRIVE_ROOT_FOLDER_ID` is now migration-only
- `@dimagi.com` email filter at OAuth was dropped during the multi-tenancy work; `ACE_ALLOWED_EMAIL_DOMAINS` is preserved as a deployment safety knob (set to a non-empty list to revert)
- Web-native opp creation works (`apps/opps/opp_creator.py` + `NewOppDialog`); first-impression polish (empty states, auto-slug, welcome flow, README) landed in PR #139 (2026-04-28)
- `apps/service_accounts/` has full credential registry + impersonation + audit log infrastructure

## Known Considerations
- Drive is the source of truth — don't propose Postgres mirrors of opp content
- Visualization view is refresh-to-update, not live-pushed
- Plugin-driven dynamic skill registry — adding a skill is a one-file edit in `../ace`, not in this repo
- Per-user CLI credentials are explicitly future work (`docs/plans/2026-04-18-per-user-cli-credentials.md`) — relevant to "web-only user runs their own Claude" story
- The team uses tags (free-form) on `OppWorkspace` to group sibling opps; multi-run was deliberately removed
- For first-impression / new-user-polish work, prefer ONE bundled PR over per-finding splits (validated 2026-04-28-user-value)
