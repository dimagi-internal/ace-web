# Archived docs

Docs that describe code or approaches that no longer exist. Kept for history,
**not** as guidance — nothing here matches current ace-web. Most were moved on
2026-09-18 by the doc-regeneration pass (see the PR that added this file); later
additions say when their code was retired. Older plans and
specs that still cite these files by their original `docs/learnings/…`,
`docs/plans/…` or `docs/specs/…` paths mean the copy here.

| File | Why it's archived |
|---|---|
| `learnings/api-envelope-convention.md` | Prescribes the `{data, error}` envelope, retired in PR #352 (RFC 7807 problem+json + bare payloads since). |
| `learnings/sse-django-async.md` | SSE chat transport, replaced by WebSocket in Phase 3; the chat stream itself was retired in PR #687. |
| `learnings/stream-resume-vercel-open-agents.md` | Stream-resume hazards in ace-web's own chat stream, retired in PR #687 (chat is canopy-hosted). |
| `specs/2026-04-09-phase-3-multi-player-design.md` | ace-web-hosted multi-player chat (drafts, presence, `SessionConsumer`), retired in PR #687. |
| `plans/2026-04-09-3-multi-player.md` | Implementation plan for the above. |
| `plans/2026-05-05-stream-reconnect-resilience.md` | Hazard-1 fix for the retired chat stream. |
| `plans/2026-05-15-videos-structured-editor.md` | Never-built design sketch; superseded by the React beat editor (PR #391). |
| `learnings/cloud-emulator-snapshot-persistence.md` | AVD snapshot semantics of the cloud mobile emulator's AMI bake (`infra/mobile-ami/`), retired 2026-10-14 — Android emulators are now canopy-web capability leases claimed by ACE. |
| `specs/2026-05-10-phase5-cloud-mobile-integration-design.md` | ACE Phase 5/6 ↔ the ace-web cloud mobile runner (`apps/mobile/`, `/api/mobile/*`), retired 2026-10-14. |
| `plans/2026-05-09-mobile-cloud-runner-poc.md` | Implementation plan for the cloud mobile runner, retired 2026-10-14. |
| `plans/2026-09-09-mobile-emulator-iac.md` | Adopted the emulator's AWS resources into the `ace-mobile` CloudFormation stack; the emulator and that template were retired 2026-10-14. |
