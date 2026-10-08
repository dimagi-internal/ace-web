/**
 * The Workbench's Phases decisions panel reads decision lineage from the run
 * page's `LineageProvider`: an origin badge on each row, the history in the
 * row detail, and the page-level filter narrowing the panel. Lineage payload:
 * the real spark clone (`sparkLineage.fixture.ts`).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Decision } from "@/api/types.ws";
import { LineageProvider } from "@/components/opps/decisions/lineage/Lineage";
import type { LineageFilter } from "@/components/opps/decisions/lineage/lineageDisplay";
import { MEMBER_LINEAGE } from "@/components/opps/decisions/lineage/__tests__/sparkLineage.fixture";
import { DecisionsPanel } from "../DecisionsPanel";

function dec(over: Partial<Decision> = {}): Decision {
  return {
    id: "row",
    phase: "design",
    phase_raw: "1-design",
    skill: "idea-to-pdd",
    question: "q",
    ai_default: "a",
    override: "",
    options_considered: [],
    source: "",
    status: "ai-default",
    notes: "",
    override_reasoning: "",
    evidence_basis: "stated",
    conflict_signals: [],
    ...over,
  };
}

const ROWS = [
  dec({ id: "working-language", question: "Which working languages?" }),
  dec({ id: "program-reuse-vs-create-spark", question: "Reuse the program?" }),
];

function renderPanel(filter: LineageFilter = "all") {
  render(
    <LineageProvider
      value={{ lineage: MEMBER_LINEAGE, filter, setFilter: () => {}, plain: false }}
    >
      <DecisionsPanel phase="design" decisions={ROWS} />
    </LineageProvider>,
  );
  fireEvent.click(screen.getByText("Decisions").closest("button")!);
}

describe("DecisionsPanel lineage", () => {
  it("badges each row with where it came from", () => {
    renderPanel();
    expect(screen.getByText("decided by ACE in run 20260925-1536 (25 Sep), carried unchanged")).toBeTruthy();
    expect(screen.getByText("changed by ACE when copied into this workspace")).toBeTruthy();
  });

  it("shows the history in the row detail when the value evolved", () => {
    renderPanel();
    fireEvent.click(screen.getByText("Reuse the program?"));
    expect(screen.getByText("How this decision evolved")).toBeTruthy();
  });

  it("shows no history for a decision carried over unchanged", () => {
    renderPanel();
    fireEvent.click(screen.getByText("Which working languages?"));
    expect(screen.queryByText("How this decision evolved")).toBeNull();
  });

  it("follows the run page's filter", () => {
    renderPanel("changed");
    expect(screen.queryByText("Which working languages?")).toBeNull();
    expect(screen.getByText("Reuse the program?")).toBeTruthy();
  });

  it("renders as before with no lineage", () => {
    render(<DecisionsPanel phase="design" decisions={ROWS} />);
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    expect(screen.getByText("Which working languages?")).toBeTruthy();
    expect(screen.queryByText(/carried unchanged/)).toBeNull();
  });
});
