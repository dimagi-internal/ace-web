import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Decision } from "@/api/types.ws";
import { DecisionsPanel } from "../DecisionsPanel";

function dec(over: Partial<Decision> = {}): Decision {
  return {
    id: "row-1",
    phase: "design",
    phase_raw: "design",
    skill: "idea-to-pdd",
    question: "How many visit instruments?",
    ai_default: "two linked forms",
    override: "",
    options_considered: ["one form", "two linked forms"],
    source: "idea-to-pdd",
    status: "ai-default",
    notes: "",
    override_reasoning: "",
    evidence_basis: "stated",
    conflict_signals: [],
    ...over,
  };
}

const expandPanel = () =>
  fireEvent.click(screen.getByText("Decisions").closest("button")!);
const expandRow = () => fireEvent.click(screen.getByText("How many visit instruments?"));

describe("DecisionsPanel — v4 evidence_basis / conflict_signals", () => {
  it("flags a conflicting row with a 'conflicting' chip in the collapsed list", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[
          dec({
            evidence_basis: "conflicting",
            conflict_signals: ["visited twice", "one instrument only"],
          }),
        ]}
      />,
    );
    expandPanel(); // panel open, row still collapsed
    expect(screen.getByText("conflicting")).toBeInTheDocument();
  });

  it("shows a quieter 'inferred' chip in the collapsed list", () => {
    render(
      <DecisionsPanel phase="design" decisions={[dec({ evidence_basis: "inferred" })]} />,
    );
    expandPanel();
    expect(screen.getByText("inferred")).toBeInTheDocument();
  });

  it("shows NO evidence chip for a stated (legacy) row", () => {
    render(<DecisionsPanel phase="design" decisions={[dec()]} />);
    expandPanel();
    expect(screen.queryByText("conflicting")).toBeNull();
    expect(screen.queryByText("inferred")).toBeNull();
    expect(screen.queryByText("stated")).toBeNull();
  });

  it("renders the competing signals as a list when a conflicting row is expanded", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[
          dec({
            evidence_basis: "conflicting",
            conflict_signals: ["visited twice", "one instrument only"],
          }),
        ]}
      />,
    );
    expandPanel();
    expandRow();
    expect(screen.getByText("Conflicting source signals")).toBeInTheDocument();
    expect(screen.getByText("visited twice")).toBeInTheDocument();
    expect(screen.getByText("one instrument only")).toBeInTheDocument();
    // Evidence basis is surfaced in the detail body too.
    expect(screen.getByText("Evidence basis")).toBeInTheDocument();
  });

  it("does not add an Evidence basis detail row for a stated row", () => {
    render(<DecisionsPanel phase="design" decisions={[dec()]} />);
    expandPanel();
    expandRow();
    expect(screen.queryByText("Evidence basis")).toBeNull();
    expect(screen.queryByText("Conflicting source signals")).toBeNull();
  });
});
