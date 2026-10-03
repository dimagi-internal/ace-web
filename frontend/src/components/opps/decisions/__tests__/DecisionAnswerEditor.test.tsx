import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Decision } from "@/api/types.ws";
import { DecisionAnswerEditor } from "../DecisionAnswerEditor";

function dec(over: Partial<Decision> = {}): Decision {
  return {
    id: "row-1",
    phase: "design",
    phase_raw: "1-design",
    skill: "idea-to-pdd",
    question: "Who is the target population?",
    ai_default: "FLWs in rural Kenya",
    override: "",
    options_considered: ["FLWs in rural Kenya", "FLWs in rural Tanzania"],
    source: "idea-to-pdd",
    status: "ai-default",
    notes: "",
    override_reasoning: "",
    evidence_basis: "stated",
    conflict_signals: [],
    ...over,
  };
}

/**
 * `voice` is who is being spoken to; a pick commits as it happens on both
 * surfaces (the anonymous-only `confirm` mode was removed, 2026-10-03).
 */
describe("DecisionAnswerEditor", () => {
  it("speaks the Workbench's vocabulary in the console voice", () => {
    render(
      <DecisionAnswerEditor
        decision={dec({ override: "FLWs in rural Tanzania" })}
        effectiveValue="FLWs in rural Tanzania"
        effectiveReason=""
        voice="console"
        onCommit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    expect(screen.getByText("Revert")).toBeTruthy();
    expect(screen.getByText("Add override reason")).toBeTruthy();
  });

  it("speaks a partner's vocabulary in the partner voice, with the same immediate commit", () => {
    render(
      <DecisionAnswerEditor
        decision={dec({ override: "FLWs in rural Tanzania" })}
        effectiveValue="FLWs in rural Tanzania"
        effectiveReason=""
        voice="partner"
        onCommit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    expect(screen.getByText("Restore the AI default")).toBeTruthy();
    expect(screen.getByText("Write in a different answer")).toBeTruthy();
    expect(screen.queryByText("Revert")).toBeNull();
  });

  it("keeps one set of field labels across both voices", () => {
    // aria-labels are the contract with assistive tech and with tests —
    // the visible copy differs, these must not.
    for (const voice of ["console", "partner"] as const) {
      const { unmount } = render(
        <DecisionAnswerEditor
          decision={dec()}
          effectiveValue="FLWs in rural Kenya"
          effectiveReason=""
          voice={voice}
          onCommit={vi.fn()}
        />,
      );
      fireEvent.click(
        screen.getByRole("button", {
          name: voice === "console" ? "Add override reason" : "Write in a different answer",
        }),
      );
      expect(
        screen.getByLabelText("Override reason for: Who is the target population?"),
      ).toBeTruthy();
      expect(
        screen.getByLabelText("New option for: Who is the target population?"),
      ).toBeTruthy();
      unmount();
    }
  });

  it("commits a pill click straight away ", () => {
    const onCommit = vi.fn();
    render(
      <DecisionAnswerEditor
        decision={dec()}
        effectiveValue="FLWs in rural Kenya"
        effectiveReason=""
        voice="partner"
        onCommit={onCommit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Tanzania/ }));
    expect(onCommit).toHaveBeenCalledWith("FLWs in rural Tanzania", "");
    // Committed on click — no Save step.
    expect(screen.queryByText("Save this answer")).toBeNull();
  });

  it("shows a failed immediate save instead of snapping back in silence", () => {
    // In immediate mode there is no draft block open to hang an error
    // off, so a server refusal would otherwise just look like the pill
    // click never happened.
    render(
      <DecisionAnswerEditor
        decision={dec()}
        effectiveValue="FLWs in rural Kenya"
        effectiveReason=""
        voice="partner"
        onCommit={vi.fn()}
        error="Give it a few minutes before sending another change."
      />,
    );
    expect(screen.getByText(/Give it a few minutes/)).toBeTruthy();
  });
});
