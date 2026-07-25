import { fireEvent, render, screen, within } from "@testing-library/react";
import { useReducer } from "react";
import { describe, expect, it, vi } from "vitest";

import type { Decision } from "@/api/types.ws";
import { DecisionsPanel } from "../DecisionsPanel";
import {
  decisionsReducer,
  initialDecisionsEditState,
} from "../decisions/decisionsReducer";

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
    evidence_basis: "stated",
    conflict_signals: [],
    ...over,
  };
}

function expandPanelAndRow() {
  fireEvent.click(screen.getByText("Decisions").closest("button")!);
  fireEvent.click(screen.getByText("Who is the target population?"));
}

/** Chip helper — the status chip is the element whose text starts with the
 * status word; disambiguated from pills/summary by its uppercase class. */
function statusChip() {
  const chips = screen
    .getAllByText(/ai-default|overridden/i)
    .filter((el) => /uppercase/.test(el.className));
  expect(chips).toHaveLength(1);
  return chips[0];
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

  it("clicking a non-default option pill stages the edit immediately (no Save step)", () => {
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
    fireEvent.click(screen.getByRole("button", { name: /FLWs in rural Tanzania/i }));
    expect(onEdit).toHaveBeenCalledWith("row-1", "FLWs in rural Tanzania", undefined);
  });

  it("renders no per-row Save button", () => {
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
    expect(screen.queryByRole("button", { name: /^save$/i })).toBeNull();
  });

  it("clicking the current AI default pill is a no-op (radio semantics)", () => {
    const onEdit = vi.fn();
    const onRevert = vi.fn();
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[]}
        onEdit={onEdit}
        onRevert={onRevert}
      />,
    );
    expandPanelAndRow();
    const pressed = screen
      .getAllByRole("button", { pressed: true })
      .filter((b) => /FLWs in rural Kenya/.test(b.textContent ?? ""));
    expect(pressed).toHaveLength(1);
    fireEvent.click(pressed[0]);
    expect(onEdit).not.toHaveBeenCalled();
    expect(onRevert).not.toHaveBeenCalled();
  });

  it("clicking the AI default pill while an edit is pending reverts the row", () => {
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
    fireEvent.click(screen.getByRole("button", { name: /FLWs in rural Kenya/i }));
    expect(onRevert).toHaveBeenCalledWith("row-1");
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("the override-reason textarea stages on blur", () => {
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
    fireEvent.blur(reason);
    expect(onEdit).toHaveBeenCalledWith(
      "row-1",
      "FLWs in rural Tanzania",
      "LLO confirmed Tanzania",
    );
  });

  it("the new-option input stages on blur and wins over the pill value", () => {
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
    fireEvent.click(screen.getByRole("button", { name: /add override reason/i }));
    const newOpt = screen.getByLabelText(/new option for: Who is the target/i);
    fireEvent.change(newOpt, { target: { value: "FLWs in rural Rwanda" } });
    fireEvent.blur(newOpt);
    expect(onEdit).toHaveBeenCalledWith("row-1", "FLWs in rural Rwanda", undefined);
  });

  it("picking a pill carries the in-progress draft reason with it", () => {
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
    fireEvent.click(screen.getByRole("button", { name: /add override reason/i }));
    const reason = screen.getByLabelText(/override reason for: Who is the target/i);
    fireEvent.change(reason, { target: { value: "typed before picking" } });
    fireEvent.click(screen.getByRole("button", { name: /FLWs in rural Tanzania/i }));
    expect(onEdit).toHaveBeenLastCalledWith(
      "row-1",
      "FLWs in rural Tanzania",
      "typed before picking",
    );
  });

  it("chip reads ai-default (emerald) when nothing is staged or overridden", () => {
    render(<DecisionsPanel phase="design" decisions={[dec()]} />);
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    const chip = statusChip();
    expect(chip.textContent).toMatch(/^ai-default$/i);
    expect(chip.className).toMatch(/emerald/);
  });

  it("chip reads overridden (sky) for a committed run override", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec({ override: "FLWs in rural Tanzania", status: "overridden" })]}
      />,
    );
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    const chip = statusChip();
    expect(chip.textContent).toMatch(/^overridden$/i);
    expect(chip.className).toMatch(/sky/);
  });

  it("chip reads 'overridden · pending' (violet) for a buffered edit", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[{ row_id: "row-1", new_answer: "FLWs in rural Tanzania" }]}
        onEdit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    const chip = statusChip();
    expect(chip.textContent).toMatch(/overridden · pending/i);
    expect(chip.className).toMatch(/violet/);
  });

  it("chip falls back to ai-default when the buffered edit equals the default with no reason", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec({ override: "FLWs in rural Tanzania", status: "overridden" })]}
        editBuffer={[{ row_id: "row-1", new_answer: "FLWs in rural Kenya" }]}
        onEdit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    const chip = statusChip();
    expect(chip.textContent).toMatch(/^ai-default$/i);
    expect(chip.className).toMatch(/emerald/);
  });

  it("pill click flips the chip to pending and updates the header value (integration with reducer)", () => {
    function Harness() {
      const [state, dispatch] = useReducer(
        decisionsReducer,
        undefined,
        initialDecisionsEditState,
      );
      return (
        <DecisionsPanel
          phase="design"
          decisions={[dec()]}
          editBuffer={state.buffer}
          onEdit={(row_id, new_answer, override_reasoning) =>
            dispatch({ type: "APPLY_EDIT", row_id, new_answer, override_reasoning })
          }
          onRevert={(row_id) => dispatch({ type: "REVERT_EDIT", row_id })}
        />
      );
    }
    render(<Harness />);
    expandPanelAndRow();
    fireEvent.click(screen.getByRole("button", { name: /FLWs in rural Tanzania/i }));
    const chip = statusChip();
    expect(chip.textContent).toMatch(/overridden · pending/i);
    // Header `→ value` follows the staged pick. The value renders in the
    // header summary and the pill; assert at least the summary updated.
    expect(screen.getAllByText("FLWs in rural Tanzania").length).toBeGreaterThanOrEqual(2);
    // Revert restores AI-DEFAULT.
    fireEvent.click(screen.getByRole("button", { name: /^revert$/i }));
    expect(statusChip().textContent).toMatch(/^ai-default$/i);
  });

  it("saved override renders as overridden (sky) and drives the header value", () => {
    // Buffer cleared after a Save to Drive; the saved_overrides overlay
    // keeps the row honest. Without this, saving looks like data loss.
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[]}
        savedOverrides={{
          "row-1": {
            override: "FLWs in rural Tanzania",
            reasoning: "expert reviewed",
          },
        }}
        onEdit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    const chip = statusChip();
    expect(chip.textContent).toMatch(/^overridden$/i);
    expect(chip.className).toMatch(/sky/);
    // Header `→ value` follows the saved override.
    expect(screen.getByText("FLWs in rural Tanzania")).toBeInTheDocument();
  });

  it("saved override reasoning shows in the Override reason detail row", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        savedOverrides={{
          "row-1": {
            override: "FLWs in rural Tanzania",
            reasoning: "expert reviewed on 7/24",
          },
        }}
      />,
    );
    expandPanelAndRow();
    expect(screen.getByText(/expert reviewed on 7\/24/i)).toBeInTheDocument();
  });

  it("pending buffer edit beats a saved override (precedence)", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[{ row_id: "row-1", new_answer: "FLWs in rural Uganda" }]}
        savedOverrides={{
          "row-1": { override: "FLWs in rural Tanzania" },
        }}
        onEdit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    const chip = statusChip();
    expect(chip.textContent).toMatch(/overridden · pending/i);
    // Header shows the pending value, not the saved one.
    expect(screen.getByText("FLWs in rural Uganda")).toBeInTheDocument();
  });

  it("saved override beats the committed run override (precedence)", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[
          dec({ override: "FLWs in rural Uganda", status: "overridden" }),
        ]}
        savedOverrides={{
          "row-1": { override: "FLWs in rural Tanzania" },
        }}
      />,
    );
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    expect(screen.getByText("FLWs in rural Tanzania")).toBeInTheDocument();
  });

  it("keeps the 'ai' marker on the AI's original pill after an override is staged", () => {
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[{ row_id: "row-1", new_answer: "FLWs in rural Tanzania" }]}
        onEdit={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    expandPanelAndRow();
    const kenyaPill = screen.getByRole("button", { name: /FLWs in rural Kenya/i });
    expect(within(kenyaPill).getByText("ai")).toBeInTheDocument();
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
    expect(
      screen.queryByLabelText(/override reason for: Who is the target/i),
    ).toBeNull();
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

  it("blurring the reason empty with answer == ai_default reverts a pending edit", () => {
    const onEdit = vi.fn();
    const onRevert = vi.fn();
    render(
      <DecisionsPanel
        phase="design"
        decisions={[dec()]}
        editBuffer={[{ row_id: "row-1", new_answer: "FLWs in rural Kenya" }]}
        onEdit={onEdit}
        onRevert={onRevert}
      />,
    );
    expandPanelAndRow();
    // Pending edit equals the AI default and has no reason. Opening the
    // reason editor and blurring it empty should collapse the edit into
    // a revert rather than stage a meaningless override.
    fireEvent.click(screen.getByRole("button", { name: /add override reason/i }));
    const reason = screen.getByLabelText(/override reason for: Who is the target/i);
    fireEvent.blur(reason);
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
