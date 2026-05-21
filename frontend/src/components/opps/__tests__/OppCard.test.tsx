import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { OppCardItem } from "../OppCard";
import type { OppCard as OppCardData } from "../../../api/types.ws";

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
