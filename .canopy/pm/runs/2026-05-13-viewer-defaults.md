## 2026-05-13 — viewer-defaults (human-gated)

Ninth cycle on ace-web; first run after a ~2-week scout pause. Lens
framing reset by the user at invocation:

> "general use of ace-web, to date I'm the only one using it and I
>  mostly prefer the CLI so we're looking for ways to make the basic
>  function better. I mostly use it as a view tool, not a run tool.
>  I have another agent trying to iterate on running with it"

Important context update: the "aspirational third-party web-only user"
lens in `context.md` is **not** what the sole real user is exercising.
Real usage is solo, view-heavy, on opps a *different* agent is iterating.
The productive scout target is whatever makes opp/run scanning faster
and more legible for one person flipping between views.

### Findings (scouted)

1. **Workbench middle pane starts empty.** `OppWorkbenchPage.tsx:174-176`
   shows "Select a step. Click a row in the lifecycle to see its details."
   on every cold open. As a view tool, one extra click per opp visit.
2. **Workbench chat pane (400px) is dead space for view-only use.**
   Reading a PDD or app-summary in a 560px StepDetail column on a 1440
   viewport is uncomfortable.
3. **No keyboard navigation anywhere.** Confirmed by grep — zero
   global `useHotkeys`/`onKeyDown` outside form inputs.
4. **No "what changed since you last looked" hint** on `/opps`. With
   another agent iterating, the sole human viewer has no quiet signal
   for "this opp moved".

### Dispositions

1. **Auto-select most-interesting step on Workbench load** — `Redirect`.
   User reframed: *"I like the phases view the best, let's switch that to
   being the default 1st view we see."* So the underlying friction was
   real, but the fix is one layer up: stop landing on the 3-pane
   Workbench at all. Re-scoped to "switch the default view to Phases".
2. **Collapsible Workbench chat pane** — `Do it`.
3. **Keyboard nav across viewer surfaces** — `Close`.
   Reason: *"Too speculative — needs a clearer pain point."* Learning:
   for solo view-mode use, don't propose generic keyboard nav without a
   concrete moment-by-moment workflow trigger.
4. **"What changed since you last looked" indicator** — not proposed in
   the top-3, holding for a later cycle.

### Do it

1. **Switch the default Opp view from Workbench to Phases** —
   Effort: S — Status: shipped (PR pending — see Verify section).
   - Branch: `feat/workbench-viewer-defaults`
   - What:
     - `frontend/src/pages/OppWorkbenchPage.tsx` — `useViewMode("workbench")`
       → `useViewMode("phase")`. Reordered `VIEW_TABS` to put Phases
       first so the tab strip matches the new default.
   - URL contract: `useViewMode` omits `?view=` when the active view
     equals the default, so existing bookmarks of bare `/opps/<slug>`
     now resolve to Phases. Bookmarks of `?view=workbench` continue to
     work. Phase tab clicks produce a bare URL; Workbench clicks
     produce `?view=workbench`.

2. **Collapsible Workbench chat pane** — Effort: S —
   Status: shipped (same PR).
   - What:
     - `frontend/src/hooks/useChatPaneCollapsed.ts` — new
       localStorage-backed hook (`ace.workbench.chatPaneCollapsed`).
       Try/catch around storage access so private-mode degrades to
       per-tab.
     - `frontend/src/hooks/useChatPaneCollapsed.test.ts` — 4 vitest
       cases (default, persisted-read, toggle persists, setCollapsed
       persists). jsdom in this vitest config has no Storage shim, so
       installed a minimal in-memory mock via `vi.stubGlobal`. Worth
       noting for future tests touching localStorage.
     - `OppWorkbenchPage.tsx` — when `chatCollapsed`, render the right
       aside as an 8px-wide rail with a left-chevron expand button;
       SkillList shrinks to a fixed `w-[440px]` and `StepDetailPane`
       becomes `flex-1` so the freed pixels flow to the artifact
       reading column (the original layout had SkillList as `flex-1`
       which would have absorbed the freed space into the lifecycle
       column, defeating the stated goal). When expanded, the original
       layout returns (SkillList `flex-1`, StepDetail `w-[560px]`,
       chat `w-[400px]`) plus a small Chat header strip with a
       right-chevron collapse button.

### Backlog

- "What changed since you last looked" badge on /opps — per-user
  `last_viewed_at` per opp, dot when Drive `updated_at` is newer.
  M effort, schema add. Real signal for sole-user-monitoring-other-
  agent's-work pattern.
- Auto-select-most-interesting step on the Workbench view (for when
  the user *does* toggle to Workbench from Phases) — preserved from
  Proposal 1's original framing. S effort.

### Closed

1. **Global keyboard navigation** — Why: *"Too speculative — needs a
   clearer pain point."*
   Learning: for solo view-mode workflows, don't propose generic
   keyboard nav without an explicit "this exact sequence of clicks
   keeps frustrating me" trigger. Logged in `learnings.md`.

### Verify (Phase 5)

- pytest: not exercised (no Python changes).
- ruff: `apps config` — All checks passed.
- bunx tsc -b: clean.
- bunx vitest run: 27/27 passing (4 new useChatPaneCollapsed tests +
  existing 23).
- Manual layout check: deferred to post-merge live verification at
  `https://labs.connect.dimagi.com/ace/w/dimagi-team/opps/<slug>` —
  matches the project precedent that pure UI changes can ship on tsc
  + vitest + a written manual test plan (per
  `learnings.md` 2026-04-28).

### Meta-observations

- **Redirect → reframe up a layer.** Proposal 1 framed the friction as
  "the Workbench middle pane is empty on cold load." The user's
  redirect reframed it as "stop opening the Workbench at all by
  default." Same friction, one level higher in the UI stack, a
  one-line fix instead of a priority-ordered picker. Pattern to keep:
  when scout findings hint at a deeper layout problem, ask the user
  before proposing a workaround that adds local logic.
- **Bundled PR matches the project rhythm.** Two thematically coherent
  items ("viewer-mode defaults on the Opp Workbench") in one PR.
  Validated by past 4 cycles' user preference for bundling.
- **localStorage in vitest needs an explicit shim in this config.**
  `useChatPaneCollapsed.test.ts` had to stub `localStorage` via
  `vi.stubGlobal` because jsdom v22's Storage shim isn't wired in
  this vitest setup. If future tests need localStorage, either lift
  this shim into `src/test/setup.ts` or repeat the per-test mock.

### Universal-improvement candidates

- **"When scout findings hint at a layout-level issue, ask before
  proposing a workaround."** Single observation today (Proposal 1
  redirect to "switch default view" was strictly cleaner than the
  scoped auto-select logic). Hold for one more confirming case
  before pitching as a canopy lesson.
