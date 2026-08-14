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
 * The two axes this editor varies on are independent, and were coupled
 * before: `voice` is who is being spoken to, `commitMode` is when a
 * change becomes durable. Coupling them meant the public surface could
 * not adopt the Workbench's immediacy without also adopting the word
 * "override", which a partner has never met.
 */
describe("DecisionAnswerEditor", () => {
  it("speaks the Workbench's vocabulary in the console voice", () => {
    render(
      <DecisionAnswerEditor
        decision={dec({ override: "FLWs in rural Tanzania" })}
        effectiveValue="FLWs in rural Tanzania"
        effectiveReason=""
        voice="console"
        commitMode="immediate"
        onCommit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    expect(screen.getByText("Revert")).toBeTruthy();
    expect(screen.getByText("Add override reason")).toBeTruthy();
  });

  it("speaks a partner's vocabulary in the partner voice, at the SAME commit mode", () => {
    render(
      <DecisionAnswerEditor
        decision={dec({ override: "FLWs in rural Tanzania" })}
        effectiveValue="FLWs in rural Tanzania"
        effectiveReason=""
        voice="partner"
        commitMode="immediate"
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
          commitMode="confirm"
          onCommit={vi.fn()}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: /Tanzania/ }));
      expect(
        screen.getByLabelText("Override reason for: Who is the target population?"),
      ).toBeTruthy();
      expect(
        screen.getByLabelText("New option for: Who is the target population?"),
      ).toBeTruthy();
      unmount();
    }
  });

  it("commits a pill click straight away in immediate mode", () => {
    const onCommit = vi.fn();
    render(
      <DecisionAnswerEditor
        decision={dec()}
        effectiveValue="FLWs in rural Kenya"
        effectiveReason=""
        voice="partner"
        commitMode="immediate"
        onCommit={onCommit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Tanzania/ }));
    expect(onCommit).toHaveBeenCalledWith("FLWs in rural Tanzania", "");
    // Nothing to confirm — the whole point.
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
        commitMode="immediate"
        onCommit={vi.fn()}
        error="Give it a few minutes before sending another change."
      />,
    );
    expect(screen.getByText(/Give it a few minutes/)).toBeTruthy();
  });
});
