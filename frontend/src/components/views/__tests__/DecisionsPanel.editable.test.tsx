import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Decision } from "@/api/types.ws";
import { DecisionsPanel } from "../DecisionsPanel";

function dec(over: Partial<Decision> = {}): Decision {
  return {
    id: "row-1",
    phase: "design",
    phase_raw: "design",
    skill: "idea-to-pdd",
    question: "Who is the target population?",
    ai_default: "FLWs in rural Kenya",
    override: "",
    options_considered: ["FLWs in rural Kenya", "FLWs in rural Tanzania", "FLWs in rural Uganda"],
    source: "idea-to-pdd",
    status: "ai-default",
    notes: "",
    override_reasoning: "",
    ...over,
  };
}

function expandPanelAndRow() {
  fireEvent.click(screen.getByText("Decisions").closest("button")!);
  fireEvent.click(screen.getByText("Who is the target population?"));
}

describe("DecisionsPanel — edit mode", () => {
  it("renders read-only options when no onEdit prop", () => {
    render(<DecisionsPanel phase="design" decisions={[dec()]} />);
    expandPanelAndRow();
    // No edit button exposed.
    expect(screen.queryByRole("button", { name: /override reason/i })).toBeNull();
    // Options render as plain spans, not buttons. The decisions panel
    // chevron + row toggle are still buttons, but no option pill is.
    const optionLabels = ["FLWs in rural Tanzania", "FLWs in rural Uganda"];
    for (const label of optionLabels) {
      const node = screen.getByText(label);
      expect(node.tagName.toLowerCase()).toBe("span");
    }
  });

  it("renders 'Add override reason' button when onEdit prop is supplied", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[]}
        onEdit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    expandPanelAndRow();
    expect(
      screen.getByRole("button", { name: /add override reason/i }),
    ).toBeInTheDocument();
  });

  it("clicking a non-default option pill stages an override + commits on Save", () => {
    const onEdit = vi.fn();
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[]}
        onEdit={onEdit}
        onRevert={vi.fn()}
      />,
    );
    expandPanelAndRow();
    // Click the Tanzania pill — enters edit mode.
    fireEvent.click(screen.getByRole("button", { name: /FLWs in rural Tanzania/i }));
    // Save commits the staged override.
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onEdit).toHaveBeenCalledWith("row-1", "FLWs in rural Tanzania", undefined);
  });

  it("clicking the current AI default pill is a no-op (no edit mode)", () => {
    const onEdit = vi.fn();
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[]}
        onEdit={onEdit}
        onRevert={vi.fn()}
      />,
    );
    expandPanelAndRow();
    // The AI default pill is the one with aria-pressed=true while no edit
    // is in progress. There are two "FLWs in rural Kenya" matches on screen
    // (the pill + the header summary line) so we have to disambiguate by
    // role + pressed-state.
    const pressed = screen
      .getAllByRole("button", { pressed: true })
      .filter((b) => /FLWs in rural Kenya/.test(b.textContent ?? ""));
    expect(pressed).toHaveLength(1);
    fireEvent.click(pressed[0]);
    // No Save button — edit mode never opened.
    expect(screen.queryByRole("button", { name: /^save$/i })).toBeNull();
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("'Add override reason' opens textarea + new-option input; Save passes the reason", () => {
    const onEdit = vi.fn();
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec({ override: "FLWs in rural Tanzania", status: "overridden" })]}
        editBuffer={[]}
        onEdit={onEdit}
        onRevert={vi.fn()}
      />,
    );
    expandPanelAndRow();
    fireEvent.click(screen.getByRole("button", { name: /add override reason/i }));
    const reason = screen.getByLabelText(/override reason for: Who is the target/i);
    fireEvent.change(reason, { target: { value: "LLO confirmed Tanzania" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onEdit).toHaveBeenCalledWith(
      "row-1",
      "FLWs in rural Tanzania",
      "LLO confirmed Tanzania",
    );
  });

  it("typing a new option overrides the pill selection on Save", () => {
    const onEdit = vi.fn();
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[]}
        onEdit={onEdit}
        onRevert={vi.fn()}
      />,
    );
    expandPanelAndRow();
    // Enter edit mode by clicking Tanzania, then type a new option.
    fireEvent.click(screen.getByRole("button", { name: /FLWs in rural Tanzania/i }));
    const newOpt = screen.getByLabelText(/new option for: Who is the target/i);
    fireEvent.change(newOpt, { target: { value: "FLWs in rural Rwanda" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    // New option wins over the pill click.
    expect(onEdit).toHaveBeenCalledWith("row-1", "FLWs in rural Rwanda", undefined);
  });

  it("shows an 'edited' badge and the effective value when row is in buffer", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[{ row_id: "row-1", new_answer: "FLWs in rural Rwanda" }]}
        onEdit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    // Effective value renders in the header summary.
    expect(screen.getByText("FLWs in rural Rwanda")).toBeInTheDocument();
    expect(screen.getByText(/edited/i)).toBeInTheDocument();
  });

  it("shows the override reason as a detail row when set in source data", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[
          dec({
            override: "FLWs in rural Tanzania",
            status: "overridden",
            override_reasoning: "human picked Tanzania per LLO directive",
          }),
        ]}
      />,
    );
    expandPanelAndRow();
    expect(
      screen.getByText(/human picked Tanzania per LLO directive/i),
    ).toBeInTheDocument();
    // The label for the row shows up too.
    expect(screen.getByText("Override reason")).toBeInTheDocument();
  });

  it("button label flips to 'Edit override reason' once a reason exists", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[
          dec({
            override: "FLWs in rural Tanzania",
            status: "overridden",
            override_reasoning: "existing reason",
          }),
        ]}
        editBuffer={[]}
        onEdit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    expandPanelAndRow();
    expect(
      screen.getByRole("button", { name: /edit override reason/i }),
    ).toBeInTheDocument();
  });

  it("collapsing the row while editing resets the draft", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[]}
        onEdit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    const rowButton = screen.getByText("Who is the target population?").closest("button")!;
    fireEvent.click(rowButton);
    // Enter edit mode + type a partial reason.
    fireEvent.click(screen.getByRole("button", { name: /add override reason/i }));
    fireEvent.change(
      screen.getByLabelText(/override reason for: Who is the target/i),
      { target: { value: "WIP draft" } },
    );
    // Collapse the row.
    fireEvent.click(rowButton);
    // Re-expand.
    fireEvent.click(rowButton);
    // Edit mode should be off; the trigger button should be visible again.
    expect(screen.queryByRole("button", { name: /^save$/i })).toBeNull();
    expect(
      screen.getByRole("button", { name: /add override reason/i }),
    ).toBeInTheDocument();
  });

  it("reverting calls onRevert with row_id", () => {
    const onRevert = vi.fn();
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[{ row_id: "row-1", new_answer: "FLWs in rural Tanzania" }]}
        onEdit={vi.fn()}
        onRevert={onRevert}
      />,
    );
    expandPanelAndRow();
    fireEvent.click(screen.getByRole("button", { name: /^revert$/i }));
    expect(onRevert).toHaveBeenCalledWith("row-1");
  });

  it("Save with answer == ai_default and no reason calls onRevert", () => {
    const onEdit = vi.fn();
    const onRevert = vi.fn();
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[{ row_id: "row-1", new_answer: "FLWs in rural Tanzania" }]}
        onEdit={onEdit}
        onRevert={onRevert}
      />,
    );
    expandPanelAndRow();
    // We have a pending edit → 'Edit override reason' button shows up
    // because there's no reason yet, and the new-option/reason form opens
    // pre-seeded with the current selection. Click the Kenya pill (the AI
    // default) to flip back, then Save → should revert.
    fireEvent.click(screen.getByRole("button", { name: /add override reason/i }));
    fireEvent.click(screen.getByRole("button", { name: /FLWs in rural Kenya/i }));
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onRevert).toHaveBeenCalledWith("row-1");
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("renders a 'new' write-in pill when override is not in options_considered (committed)", () => {
    // A row whose `override` is a write-in value that isn't in
    // `options_considered`. The pill row should surface the write-in as
    // an extra violet "(new)" pill so the user can see the current
    // selection somewhere in the pill row — not just in the header chip.
    render(
      <DecisionsPanel
        phase="design"
        decisions={[
          dec({
            override: "FLWs in rural Rwanda",
            status: "overridden",
            override_reasoning: "human picked Rwanda",
          }),
        ]}
      />,
    );
    expandPanelAndRow();
    // The write-in label appears as a pill (separate from the row header).
    const labels = screen.getAllByText("FLWs in rural Rwanda");
    expect(labels.length).toBeGreaterThanOrEqual(2);
    // The "(new)" tag is present alongside the write-in pill.
    expect(screen.getByText("new")).toBeInTheDocument();
  });

  it("renders a 'new' write-in pill while typing in the New option field (draft preview)", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[]}
        onEdit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    expandPanelAndRow();
    fireEvent.click(screen.getByRole("button", { name: /add override reason/i }));
    const newOpt = screen.getByLabelText(/new option for: Who is the target/i);
    fireEvent.change(newOpt, { target: { value: "FLWs in rural Rwanda" } });
    // The draft write-in should preview as a pill immediately, so the
    // user can see what they're about to commit.
    expect(screen.getByText("FLWs in rural Rwanda")).toBeInTheDocument();
    expect(screen.getByText("new")).toBeInTheDocument();
  });

  it("overridden row gets a stronger background tint than ai-default rows", () => {
    // Render two decisions, one overridden and one not — confirm the
    // overridden row carries the sky-tinted background class so the
    // color flip is visible at-a-glance.
    const decisions = [
      dec({ id: "row-1", question: "Q ai", status: "ai-default" }),
      dec({
        id: "row-2",
        question: "Q overridden",
        override: "FLWs in rural Tanzania",
        status: "overridden",
      }),
    ];
    const { container } = render(
      <DecisionsPanel phase="design" decisions={decisions} />,
    );
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    const overriddenLi = screen.getByText("Q overridden").closest("li")!;
    const aiDefaultLi = screen.getByText("Q ai").closest("li")!;
    const overriddenWrap = within(overriddenLi).getByText("Q overridden")
      .closest("div");
    const aiDefaultWrap = within(aiDefaultLi).getByText("Q ai").closest("div");
    // The overridden row's outer wrapper carries the sky tint; the
    // ai-default row's does not.
    expect(overriddenWrap?.className ?? "").toMatch(/sky-500/);
    expect(aiDefaultWrap?.className ?? "").not.toMatch(/sky-500/);
    // Sanity touch on container so the test fails fast on render errors.
    expect(container).toBeTruthy();
  });
});
