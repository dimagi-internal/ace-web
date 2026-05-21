import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { OppCardItem } from "../OppCard";
import type { OppCard as OppCardData, RunSummary } from "../../../api/types.ws";

const baseOpp: OppCardData = {
  slug: "malaria-itn-app",
  display_name: "Malaria ITN App",
  labels: [],
  tags: [],
  created_at: null,
  created_by: null,
  current_run_id: null,
  current_phase: null,
  current_phase_display: null,
  current_step: null,
  current_step_display: null,
  status: "ok",
  eval_score: null,
  eval_score_pct: null,
  eval_passed: null,
  last_activity_at: null,
  run_count: 1,
  runs_summary: [],
};

function renderCard(overrides: Partial<OppCardData> = {}) {
  return render(
    <MemoryRouter>
      <OppCardItem
        opp={{ ...baseOpp, ...overrides }}
        workspaceSlug="dimagi-team"
        isExpanded={false}
        tagFilter={[]}
        canCompare={true}
        onToggleExpanded={vi.fn()}
        onToggleTag={vi.fn()}
        onRequestDelete={vi.fn()}
        onRequestCompare={vi.fn()}
      />
    </MemoryRouter>,
  );
}

describe("OppCardItem accessibility", () => {
  it("wrapper exposes the opp display name as its accessible name without leaking nested button labels", () => {
    renderCard();
    // The card-level button should be reachable by its display_name and
    // not have the slug repeated 3+ times like the pre-fix bug.
    const card = screen.getByRole("button", { name: "Malaria ITN App" });
    expect(card).toBeInTheDocument();

    // Regression guard: the wrapper's accessible name must not contain
    // the slug more than once. Pre-fix this was 3-5 occurrences.
    const accName = card.getAttribute("aria-label") ?? "";
    const slugOccurrences = (accName.match(/malaria-itn-app/g) ?? []).length;
    expect(slugOccurrences).toBeLessThanOrEqual(1);
  });

  it("falls back to slug when display_name is empty", () => {
    renderCard({ display_name: "" });
    expect(screen.getByRole("button", { name: "malaria-itn-app" })).toBeInTheDocument();
  });

  it("each icon-only action button keeps its own aria-label for screen readers", () => {
    renderCard();
    expect(
      screen.getByRole("button", { name: "Show chats linked to malaria-itn-app" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Delete malaria-itn-app" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Compare malaria-itn-app with another opp" }),
    ).toBeInTheDocument();
  });

  it("does not put a `title` attribute on the action buttons (tooltip primitive owns hover hint now)", () => {
    renderCard();
    // The pre-fix card used native `title=` attributes which were the only
    // hover affordance. With base-ui Tooltip wrapping them, the native
    // title should be gone to avoid double-tooltip behaviour.
    const del = screen.getByRole("button", { name: "Delete malaria-itn-app" });
    expect(del).not.toHaveAttribute("title");
    const cmp = screen.getByRole("button", { name: "Compare malaria-itn-app with another opp" });
    expect(cmp).not.toHaveAttribute("title");
    const chats = screen.getByRole("button", { name: "Show chats linked to malaria-itn-app" });
    expect(chats).not.toHaveAttribute("title");
  });
});

/**
 * Regression for #512.
 *
 * The Opps-list phase-chip strip used to call useOppRuns on every card
 * mount. With N opps on screen, that fanned out to N parallel
 * GET /api/w/<slug>/opps/<slug>/runs requests, blocking page render on
 * the slowest (8-12s observed at N=5). The strip now reads its data
 * from ``OppCard.runs_summary`` carried by the main /opps payload, so
 * mounting a card must NOT touch the network at all (the expanded
 * panel still lazy-fetches, but only when the user expands).
 */
describe("OppCardItem no per-card /runs fan-out (#512)", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;
  const originalFetch = global.fetch;

  beforeEach(() => {
    fetchSpy = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    global.fetch = fetchSpy as unknown as typeof global.fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  function renderCollapsedCard(runs_summary: RunSummary[]) {
    return render(
      <MemoryRouter>
        <OppCardItem
          opp={{ ...baseOpp, runs_summary }}
          workspaceSlug="dimagi-team"
          isExpanded={false}
          tagFilter={[]}
          canCompare={true}
          onToggleExpanded={vi.fn()}
          onToggleTag={vi.fn()}
          onRequestDelete={vi.fn()}
          onRequestCompare={vi.fn()}
        />
      </MemoryRouter>,
    );
  }

  it("does NOT fetch /opps/<slug>/runs when mounted with runs_summary populated", () => {
    const runs: RunSummary[] = [
      {
        run_id: "20260520-1200",
        current_phase: "scenarios-and-acceptance",
        current_phase_display: "Scenarios and acceptance",
        current_phase_ordinal: 5,
        current_step: null,
        current_step_display: null,
        mode: "auto",
        last_actor: "ace@dimagi-ai.com",
        last_actor_at: "2026-05-20T12:00:00Z",
        lifecycle_status: "in_progress",
        phases_total: 8,
        phases_done: 4,
        latest_phase_done: "design-review",
        latest_phase_done_display: "Design review",
        latest_phase_done_ordinal: 4,
      },
    ];
    renderCollapsedCard(runs);

    const runsCalls = fetchSpy.mock.calls.filter(([url]) => {
      const s = typeof url === "string" ? url : (url as Request).url;
      return /\/opps\/[^/]+\/runs(\?|$)/.test(s);
    });
    expect(runsCalls).toHaveLength(0);
  });

  it("does NOT fetch /opps/<slug>/runs even when runs_summary is empty", () => {
    renderCollapsedCard([]);

    const runsCalls = fetchSpy.mock.calls.filter(([url]) => {
      const s = typeof url === "string" ? url : (url as Request).url;
      return /\/opps\/[^/]+\/runs(\?|$)/.test(s);
    });
    expect(runsCalls).toHaveLength(0);
  });

  it("renders the phase-chip strip from runs_summary props (no network)", () => {
    const runs: RunSummary[] = [
      {
        run_id: "20260520-1200",
        current_phase: "design-review",
        current_phase_display: "Design review",
        current_phase_ordinal: 4,
        current_step: null,
        current_step_display: null,
        mode: "review",
        last_actor: null,
        last_actor_at: "2026-05-20T12:00:00Z",
        lifecycle_status: "in_progress",
        phases_total: 8,
        phases_done: 3,
        latest_phase_done: "design",
        latest_phase_done_display: "Design",
        latest_phase_done_ordinal: 3,
      },
      {
        run_id: "20260519-0900",
        current_phase: null,
        current_phase_display: null,
        current_phase_ordinal: null,
        current_step: null,
        current_step_display: null,
        mode: "auto",
        last_actor: null,
        last_actor_at: "2026-05-19T09:00:00Z",
        lifecycle_status: "complete",
        phases_total: 8,
        phases_done: 8,
        latest_phase_done: "qa-loop",
        latest_phase_done_display: "QA loop",
        latest_phase_done_ordinal: 8,
      },
    ];
    renderCollapsedCard(runs);

    // The strip's "RUNS" header is visible (the strip rendered).
    expect(screen.getByText("Runs")).toBeInTheDocument();
    // Chips read from runs_summary; "P4" comes from current_phase_ordinal,
    // "P8" from latest_phase_done_ordinal on the complete run.
    expect(screen.getByText("P4")).toBeInTheDocument();
    expect(screen.getByText("P8")).toBeInTheDocument();
    // And no fetch fired.
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
