# Multiple view modes for opps + chats — design

**Status:** Approved 2026-05-02 by jjackson (verbal — "just implement with your best judgement"). User-review gate explicitly waived.

**Premise.** ace-web's data model has Workspaces → Opps → Runs → Steps → Chats + Artifacts + Verdicts + Gates. Today users browse it through three single-projection pages: a flat opp list (`/opps`), a flat session list (`/sessions`), and a three-pane Workbench (`/opps/<slug>`). The lift in sprints 1 + 2 (PRs #178, #182) made the chat side opp-aware, but the surfaces are still single-shape.

This spec covers a view-mode system — multiple ways to look at the same data — with four shipping projections.

## Research summary

Five archetypes considered (full research in conversation log): Linear sub-issue list, Linear/Notion board, n8n + React Flow DAG, Devin/Stripe-style timeline, Granola/Slack-canvas anchored chat pane. **Board dropped on user feedback.**

## Scope — four projections

| ID | Name | Surface(s) | Inspiration |
|----|------|------------|-------------|
| **A** | Hierarchy list | `/opps` (workspace-wide) and `/opps/<slug>` (per-opp) | Linear sub-issues |
| **C** | Flow / DAG | `/opps/<slug>` (per-opp only — disabled at workspace scale) | n8n + React Flow |
| **D** | Timeline | `/opps` and `/opps/<slug>` | Devin session timeline |
| **E** | Anchored chat pane | Inside the Workbench (right pane upgrade) | Granola / Slack canvas |

A, C, D share a `<ViewSwitcher>` and URL state (`?view=`). E is independent — touches only Workbench files.

## Architecture

### Switcher

- New `frontend/src/components/views/ViewSwitcher.tsx` — pure-presentation tab strip; receives `available: ViewKind[]`, `current: ViewKind`, `onChange`.
- URL state via `?view=hierarchy|flow|timeline`. Default per surface declared on the page component.
- `ViewKind = 'hierarchy' | 'flow' | 'timeline'` exported once from `frontend/src/api/types.ts`.

### Per-view components

```
frontend/src/components/views/
  ViewSwitcher.tsx
  HierarchyView.tsx       // both /opps and /opps/<slug> — scope prop
  FlowView.tsx            // per-opp only; React Flow + dagre layout
  TimelineView.tsx        // both surfaces — scope prop
  hierarchy/
    OppRow.tsx            // expanded opp with chat children
    ChatRow.tsx
  flow/
    nodes.tsx             // ChatNode, ArtifactNode, VerdictNode, GateNode
  timeline/
    EventRow.tsx
    EventRail.tsx
```

`/opps` becomes a thin shell that picks the view based on `searchParams.view`. Today's `OppListPage` body becomes `<HierarchyView scope="workspace">`.

### Backend touchpoints

- **Hierarchy** — no new endpoints. Already supported by `/api/sessions?opp=<slug>` from sprint 1. Workspace view fetches `/api/opps/` + a single `/api/sessions?page_size=200` and groups client-side.
- **Timeline** — new `GET /api/activity/?workspace=<slug>&opp=<slug>?&type=...&since=<iso>`. Aggregates Postgres (Sessions) + Drive (artifacts via mtime, verdicts via filename, gates via `state.yaml`). Returns flat `[{ts, kind, opp_slug, title, meta}, ...]`.
- **Flow** — new `GET /api/opps/<slug>/runs/<run>/graph` returning `{nodes: [...], edges: [...]}`. Edge derivation: chat→artifact (chat linked to step, ts before artifact mtime), artifact→verdict (verdict file declares which artifact it grades), verdict→chat (chat linked to same step, ts after verdict). Depends on the run-formalization work happening in parallel.
- **Anchored chat pane (E)** — no new endpoints. Reuses existing `useSessionSocket` + `discussStep` POST.

### Phasing

| Phase | Ship | Cost (rough) | Depends on |
|-------|------|--------------|------------|
| **1** | ViewSwitcher + HierarchyView (default) | ~250 LOC FE, 0 BE | nothing |
| **2** | Workbench right-pane chat thread (E) | ~300 LOC FE, 0 BE | nothing |
| **3** | TimelineView + activity endpoint | ~250 LOC FE, ~150 LOC BE | nothing |
| **4** | FlowView + run-graph endpoint | ~400 LOC FE, ~200 LOC BE, +80kb deps | run formalization |

Order rationale: Phase 1 unlocks the switcher infrastructure for everything else. Phase 2 closes the most painful daily-use gap (jump out of Workbench to chat → stay in Workbench). Phase 3 is high-value cross-cutting and reuses existing data. Phase 4 last because it depends on the run formalization.

## Persistence

- View choice lives in the URL only (`?view=`). No per-user-saved-preference column for v1 — bookmarks + browser history cover the cases that matter.
- Tag-filter state on Hierarchy/Timeline persists in URL too (already the pattern on `/sessions`).
- Future: if users complain about losing "their" default view across sessions, add `User.preferred_views: JSONField` keyed by surface.

## Out of scope (consciously dropped or deferred)

- **Board view (B)** — dropped per user feedback during brainstorm.
- **Run-replay timeline (Devin per-run scrub)** — deferred. Timeline (D) covers most of the value; the per-run scrubber is a Phase-2 nicety.
- **Per-user saved view configs (Notion-database-style)** — deferred. URL state is enough for v1.
- **Cross-workspace search across views** — deferred. Each view stays workspace-scoped.
- **Run formalization in Drive** — out of scope for this spec; tracked separately by another agent. Phase 4's graph endpoint depends on it.

## Risks + mitigations

- **React Flow bundle size (~80kb gzipped)** — only loaded on `?view=flow`. Use route-level lazy import via `React.lazy` so default Hierarchy/Timeline visits don't pay for Flow.
- **Activity-feed N+1 against Drive** — Drive listing is the bottleneck. Cache the listing per-opp for ~30s on the server side; invalidate on opp-mutation events.
- **Graph edge derivation depends on `state.yaml` shape** — the run-formalization agent's output IS the contract for Phase 4. Block Phase 4 on their landing.

## Tests

- ViewSwitcher: vitest (if/when frontend test harness exists; otherwise integration via Playwright per existing pattern).
- HierarchyView grouping logic: pure-function tests on `groupOppsByStatus(opps, sessions)`.
- Activity endpoint: pytest covering `?since=`, `?opp=`, mixed-type filtering, deterministic ordering.
- Run-graph endpoint: pytest covering edge derivation rules with fixture data.
- Workbench right-pane chat: existing useSessionSocket tests cover the socket; new test for "no chat exists → CTA renders".

## Verification

Per the new canopy gate rule (PR #33), each phase's 3c runs against deployed prod, capturing the email's hero shot in the same pass.
