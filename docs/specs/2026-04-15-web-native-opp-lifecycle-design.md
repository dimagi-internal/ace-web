# Web-Native Opp Lifecycle — Design Spec

**Date:** 2026-04-15
**Status:** Draft — awaiting review.
**Scope:** Turn ace-web into the primary interface for building a CRISPR-Connect
opportunity end-to-end — from the initial idea through closeout. No CLI
commands required.

## 1. Overview

Today, ace-web's Opp Workbench is a read-only view of what the ACE plugin
has already done. The user is still expected to run `/ace:run <opp>` or
individual skills from a chat session, and the workbench observes the Drive
state as it changes. That gap is invisible to anyone who hasn't already
internalized the ACE plugin's command surface.

This spec closes the gap. After this lands, the "new opp" entry point, the
execution control surface, the artifact viewer, the fork/iterate loop, and
the collaboration layer all live in the web UI. The ACE plugin still does
the actual work — ace-web becomes the workspace around it.

## 2. Goals

1. **A team member with no ACE plugin knowledge can start and drive an opp
   from the web.** No memorized slash commands, no manual Drive folder
   creation.
2. **Every web action is visible and auditable.** Actions flow through an
   attached chat session, which provides a durable transcript of who did
   what, when, and why.
3. **Iteration is first-class.** Forking an opp from any completed step to
   try a different approach is a one-click operation; runs are comparable.
4. **No new execution infrastructure.** Reuse the existing chat/WebSocket/
   Drive/CLIBackend plumbing; don't add a background job runner.

## 3. Non-goals

- **Replacing the ACE plugin.** The plugin continues to own skill
  definitions, MCP servers, orchestration logic, and the actual Claude
  interaction. ace-web is the operator's front door.
- **Supporting auto mode from the web.** Auto mode (unattended execution
  that runs all phases without human review) stays as a CLI-invoked mode
  for now. The web UI is built around review mode.
- **Cross-opp orchestration.** Running many opps simultaneously, queueing,
  priorities — out of scope. One opp at a time in the UI.
- **Editing skill definitions.** Skills remain authored in the plugin
  repo and propagated into ace-web via the vendored Docker image.

## 4. Architecture

### 4.1 The attached chat model

Every opp has at most one **working chat session** attached at a time. When
a user opens `/opps/<slug>` without an attached session, one is created on
demand, seeded with the opp's context (slug, phase, current state).

The chat session is a regular ace-web `Session` (Phase 2 infrastructure)
with a new `opp_slug` column pointing back to the opp. Inside the session,
Claude has the ACE plugin installed (via the vendored plugin in the Docker
image) — so `/ace:*` commands work.

Every web action in the workbench (New opp, Run skill, Approve gate,
Fork from step, Edit artifact) translates to a user-or-system message
injected into the attached chat. Claude interprets the message and
executes the corresponding plugin skill. Artifacts land in Drive. The
workbench observes via a WebSocket nudge + `GET /api/opps/<slug>` refetch.

**Why this model:**
- Zero new execution infrastructure. No job queue. No worker process.
  No new failure modes.
- The chat IS the transcript. Every action is paired with the "why"
  (either user-typed or system-generated).
- Collaboration for free: multi-player chat from Phase 3 already lets
  several team members work on the same opp in real time.
- Forking → fresh session scoped to the new run, so each run has its own
  conversational context.

### 4.2 Data model additions

All additive. No backward-incompatible changes.

**`sessions.Session`** — add:
- `opp_slug: str` (already exists from the opps workbench "Discuss" feature)
- `opp_run_id: str | None` (already exists)
- `is_working_session: bool` — set to True when created as the primary
  chat for an opp; exactly one per (opp_slug, run_id) enforced by a
  partial unique index.

**New ORM table: `opps.OppWorkspace`** — a lightweight row per opp that
pins metadata that isn't easily stored in Drive:
- `slug: str` (PK)
- `display_name: str`
- `working_session_id: FK(Session) | None` (current working chat for the
  latest run)
- `created_by: FK(User)`
- `created_at`, `updated_at`

This is the *first* Django ORM row in the opps module (previously Drive
was the sole source of truth for opp data). We add it because:
- The working-session pointer needs to survive even if the Drive folder
  is temporarily unreachable.
- `display_name` + created-by metadata is convenient for the opp list.
- Future UX (favorites, pins, etc.) benefits from a Postgres anchor.

Drive remains the source of truth for *opp content* (idea.md, pdd.md,
artifacts, state.yaml, run history). The Postgres row is just the
workspace wrapper.

### 4.3 The eight slices

Each slice ships independently. Shown here in the recommended build
order — each builds on the previous.

#### Slice 1 — New Opp wizard

A "**+ New Opp**" button on `/opps`. Opens a modal (shadcn Dialog) with:

1. **Slug** (required) — kebab-case, validated client-side, uniqueness
   checked server-side against existing Drive folders and OppWorkspace rows.
2. **Display name** (required) — free text.
3. **Initial idea** (required) — multiline textarea; what gets written to
   `ACE/<slug>/idea.md`.
4. **Mode**: radio (auto / review, default review). Stored in `state.yaml`.
5. **Submit**.

Backend `POST /api/opps/` handler:
1. Creates the Drive folder structure `ACE/<slug>/runs/run-001/`.
2. Writes `ACE/<slug>/idea.md` and `ACE/<slug>/runs/run-001/state.yaml`.
3. Creates an `OppWorkspace` row.
4. Creates a working `Session` linked to the opp, seeded with two messages:
   - System: "Opp `<slug>` created. Initial idea is in idea.md."
   - User: `Run /ace:idea-to-pdd for <slug> in review mode.`
5. Returns `201 Created` with `{slug, working_session_slug}`.
6. Client redirects to `/opps/<slug>`.

The user lands on the workbench with the chat already running the first
skill. No CLI commands typed.

#### Slice 2 — Attached chat panel

`OppWorkbenchPage` grows a right-side chat panel. Layout reshuffles:

Before:
```
┌───────┬──────────┬──────────────┐
│ phase │ skills   │ step detail  │
│ bar   │          │              │
│       │          │              │
└───────┴──────────┴──────────────┘
```

After:
```
┌───────┬──────────┬──────────────┬──────────────┐
│ phase │ skills   │ step detail  │ chat panel   │
│ bar   │          │              │              │
│       │          │              │              │
└───────┴──────────┴──────────────┴──────────────┘
```

The chat panel is the existing `ChatPage` body component, extracted so
it's embeddable. The workbench fetches the opp's `working_session_slug`
and renders a `<ChatPanel session={slug} />` on the right.

Collapsible (users on narrow screens can hide it with a toggle button).

#### Slice 3 — Inline artifact rendering

The step detail pane currently shows a list of produced artifacts as
clickable links that open Drive. Use the new `MarkdownRenderer` component
to render the **primary artifact** inline (below the Artifacts list)
for markdown/YAML types:

- `.md` → rendered markdown (already possible)
- `.yaml` / `.yml` → rendered in a fenced code block with YAML syntax
  highlighting (rehype-highlight already in the bundle)
- `.json` → pretty-printed in a code block
- Other binary types → Drive link only

Max inline size: 50KB. Above that, show a collapsed summary with a
"Open full file in Drive" button. Artifact bodies come from the existing
`GET /api/opps/<slug>/runs/<run_id>/steps/<skill>/artifacts/<name>`
endpoint.

#### Slice 4 — Live refresh via WebSocket

Workbench subscribes to an **opp-level channel** on mount:
`opp-<slug>-<run_id>`.

When the chat session completes a turn that produced Drive side-effects
(detected by the chat consumer based on tool-use events mentioning the
Drive MCP), it broadcasts an `opp_updated` event to the opp channel. Any
workbench with that opp open reloads its snapshot via the existing
`getOpp(slug, runId)` call.

Detection rule (pragmatic): if the last completed assistant turn contains
any `tool_use` for `ace-gdrive:drive_*` or `ace-gdrive:docs_*`, emit the
nudge. False positives (turns that touched Drive but didn't change opp
state) cause a harmless extra refetch.

No polling. No crash recovery state. WebSocket already reconnects on
drop (Phase 3).

#### Slice 5 — Action buttons

Each skill row gets context-aware action buttons in the step detail pane:

- **Run** — shown when status == `pending` and all upstream deps are
  `complete`. Injects: `Run /ace:step <skill> for <slug>.`
- **Rerun** — shown when status in (`complete`, `error`, `judge-fail`).
  Injects: `Rerun /ace:step <skill> for <slug>.`
- **Approve gate** — shown when status == `gate-pending`. Injects:
  `Approve the gate for <skill>.` The ACE plugin flips the status in
  state.yaml when it sees approval.
- **Reject gate** — shown when status == `gate-pending`. Opens a small
  dialog for reason, then injects: `Reject the gate for <skill>. Reason: <text>`.

The translator between "button clicked" and "chat message" lives
server-side: `POST /api/opps/<slug>/runs/<run_id>/actions/<action>` with
the action name and optional payload. This keeps the message phrasing
centralized (and swappable without frontend changes).

#### Slice 6 — State editing (optional, can ship later)

An "**Edit**" icon on editable artifacts (PDD, state.yaml, invite-list.md,
training materials — configured per-skill in the plugin or a frontend
allowlist). Clicking opens a modal with a `<textarea>` pre-filled with the
file content and a "Save to Drive" button.

On save: `PUT /api/opps/<slug>/runs/<run_id>/artifacts/<path>` writes the
new content via the Drive client. The chat gets a system message noting
the edit. A conflict toast appears if the file's `modified_time` changed
since the modal opened (last-write-wins with warning; no merge UI for v1).

No fancy editor. No collaborative editing. The chat is the collaboration
layer; direct edits are for quick tweaks.

#### Slice 7 — Fork from step

A "**Fork from here**" button on each skill row in the step detail pane,
with a dropdown choosing the fork mode:

1. **Fork with feedback** (most common):
   - Modal collects feedback text ("What should change?")
   - Creates `runs/run-<N+1>/`
   - Copies all artifacts from the current run into the new run, EXCLUDING
     the forked step and everything after it in the pipeline
   - Creates a new working session attached to the new run, seeded with:
     system message referencing inherited state + user message: *"Rerun
     from `<skill>` with this feedback: <text>"*
   - Navigates to `/opps/<slug>/runs/<new_run_id>`

2. **Fork empty**:
   - Same as above but only inherits `idea.md`. Everything else re-runs
     from step 1 of phase 1. Useful when the idea itself was the problem.

The copying logic is a server-side loop over `artifacts_produced` in the
manifest filtered by phase ordinal < forked step's phase ordinal (and
within the same phase, skill ordinal < forked step's ordinal).

New endpoint: `POST /api/opps/<slug>/runs/<run_id>/fork` with
`{from_skill, mode, feedback?}`.

#### Slice 8 — Run selector + compare

The workbench header (`WorkbenchHeader`) grows a run selector:

- Dropdown showing all runs (newest first), with run ID, creation date,
  and a colored dot showing overall status
- Clicking a run navigates to `/opps/<slug>/runs/<run_id>`
- At the bottom of the dropdown: "**Compare runs...**" opens a modal that
  asks for two runs to compare; links to the existing
  `/opps/<slug>/compare?from=A&to=B` page

The compare page already exists (from the opp visualization plan). Slice 8
is mostly UI wiring on top of existing backend work.

## 5. API surface

New endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/opps/` | Create a new opp (slice 1) |
| `POST` | `/api/opps/<slug>/runs/<run_id>/actions/<action>` | Translate web action → chat message (slice 5) |
| `PUT` | `/api/opps/<slug>/runs/<run_id>/artifacts/<path>` | Write an edited artifact (slice 6) |
| `POST` | `/api/opps/<slug>/runs/<run_id>/fork` | Create a forked run (slice 7) |

Existing endpoints reused:
- `GET /api/opps/` — opp list (already returns what we need)
- `GET /api/opps/<slug>` — opp snapshot (already returns runs + steps)
- `GET /api/opps/<slug>/compare` — run comparison (already works)
- `POST /api/opps/<slug>/runs/<run_id>/steps/<skill>/discuss` — seed a
  discussion session (works; superseded for the primary flow by the
  working session, but still useful for ad-hoc discussion)
- All `apps/sessions/` endpoints for the chat panel

## 6. Frontend

### 6.1 Component reshuffle

The current `OppWorkbenchPage` is a 3-pane layout. After slice 2 it's
4-pane. To keep `OppWorkbenchPage.tsx` focused, we split it:

```
frontend/src/pages/
├── OppWorkbenchPage.tsx        # page shell only, composes the 4 panes
└── OppListPage.tsx              # + "New Opp" button

frontend/src/components/opps/
├── PhaseSidebar.tsx             # left
├── SkillList.tsx                # center-left (existing)
├── StepDetailPane.tsx           # center-right (existing, grows inline artifact viewer + action buttons + edit button + fork button)
├── ChatPanel.tsx                # right (new — extracts ChatPage body)
├── NewOppDialog.tsx             # new
├── RunSelector.tsx              # new
├── CompareRunsDialog.tsx        # new
├── ForkDialog.tsx               # new
├── EditArtifactDialog.tsx       # new
└── ActionButton.tsx             # generic context-aware button
```

Existing `ChatPage.tsx` is refactored so the message list + composer can
be used both as a full page and as the `<ChatPanel>` embedded component.

### 6.2 New types

```ts
// Add to frontend/src/api/types.ts
interface CreateOppPayload {
  slug: string;
  display_name: string;
  idea: string;
  mode: "auto" | "review";
}

interface CreateOppResponse {
  slug: string;
  working_session_slug: string;
}

interface ForkPayload {
  from_skill: string;
  mode: "with-feedback" | "empty";
  feedback?: string;
}

interface ForkResponse {
  new_run_id: string;
  working_session_slug: string;
}
```

## 7. Settings

No new settings. Everything uses existing `ACE_DRIVE_*` and session
config.

## 8. Testing

- **`apps/opps/tests/test_create_opp.py`** (slice 1): slug validation,
  Drive folder creation, state.yaml seeding, working session linkage.
  Uses `FakeDriveClient`.
- **`apps/opps/tests/test_actions.py`** (slice 5): each action translates
  to the correct chat message.
- **`apps/opps/tests/test_fork.py`** (slice 7): artifact copying logic —
  fork-with-feedback copies artifacts upstream of the fork point; fork-
  empty copies only idea.md; new run ID is monotonic.
- **`apps/opps/tests/test_edit_artifact.py`** (slice 6): write-through
  to Drive + conflict detection.
- **`apps/sessions/tests/test_opp_updated_broadcast.py`** (slice 4):
  consumer emits `opp_updated` after a Drive-modifying turn.
- **`e2e/tests/opp-lifecycle.spec.ts`** (Playwright): end-to-end flow —
  new opp → first skill runs → gate approval → fork from step → compare
  runs. Mocks the Claude CLI via `FakeCLIBackend`.

No dedicated frontend unit tests. Manual verification per slice.

## 9. Error handling

- **Drive unreachable on opp create** — return 503 with a clear message;
  the OppWorkspace row is created in a transaction that rolls back if
  Drive write fails.
- **Slug collision** — client-side quick check via `GET /api/opps/<slug>`
  (404 means available); server-side enforcement via OppWorkspace
  unique constraint + Drive folder existence check.
- **Working session disappears** — if the linked Session is deleted or
  archived, the workbench creates a new one on next load. The
  OppWorkspace row's pointer is repaired opportunistically.
- **Chat turn fails mid-action** — the injected user message persists
  in the transcript; the user sees the failure and can retry.
- **Fork target has no previous artifacts** — forking from step 1 with
  `with-feedback` is equivalent to `empty`; we normalize silently.
- **Artifact edit conflict** (two users editing simultaneously) — last
  write wins with a toast warning showing the other editor's name;
  no merge UI.

## 10. Migration

No destructive changes. Existing opps created before this lands:
- Show up in the opp list (reads from Drive directly; `OppWorkspace`
  rows get created lazily on first open)
- Have no working session initially; one is auto-created when the user
  opens the workbench
- Don't have any artifacts edited or forks; these are additive features

## 11. Phasing

Ship the eight slices in order. Each is independently useful; the user
should feel the experience getting better after every slice lands.

| Slice | Rough effort | Unlocks |
|-------|-------------|---------|
| 1. New Opp wizard | 1 day | Entry point for a new opp |
| 2. Attached chat panel | 1-2 days | Everything else runs through this |
| 3. Inline artifacts | 0.5 day | Readability of what was produced |
| 4. Live refresh | 1 day | Actions feel responsive without reload |
| 5. Action buttons | 1-2 days | Operations without typed commands |
| 6. State editing | 1 day | Direct tweaks without round-tripping Drive |
| 7. Fork from step | 1-2 days | Iteration and improvement loop |
| 8. Run selector + compare | 0.5 day | Multi-run navigation |

Total: ~8-11 days of engineering, but each slice ships independently and
the team can stop at any point with a product that's still better than
what's there today.

## 12. Out of scope (deliberately)

- **Auto-mode runs driven from the web.** The CLI handles unattended runs
  just fine; the web is for supervised work.
- **Background job runner.** No Celery, no Redis queues, no new
  infrastructure. The chat consumer is the only async path.
- **Rich text / WYSIWYG editing.** Slice 6 is raw markdown/YAML in a
  `<textarea>`. If the team wants more, it's a separate feature.
- **Opp sharing with external users.** All ace-web users are Dimagi team
  members authenticated via Connect OAuth; sharing is internal only. The
  existing share-token system (for read-only link sharing) is sufficient
  for outside visibility.
- **LLO self-service.** LLOs never use ace-web. This is a team tool.
