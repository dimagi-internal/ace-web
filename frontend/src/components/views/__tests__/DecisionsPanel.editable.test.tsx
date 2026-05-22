import { fireEvent, render, screen } from "@testing-library/react";
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
    default: "FLWs in rural Kenya",
    options_considered: [],
    source: "idea-to-pdd",
    status: "applied",
    notes: "",
    ...over,
  };
}

describe("DecisionsPanel — edit mode", () => {
  it("renders read-only when no onEdit prop", () => {
    render(<DecisionsPanel phase="design" decisions={[dec()]} />);
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    fireEvent.click(screen.getByText("Who is the target population?"));
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("renders edit affordance when onEdit prop is supplied", () => {
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
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    fireEvent.click(screen.getByText("Who is the target population?"));
    expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument();
  });

  it("clicking Edit reveals a textbox prefilled with the current default", () => {
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
    fireEvent.click(screen.getByText("Who is the target population?"));
    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    const textbox = screen.getByRole("textbox") as HTMLInputElement | HTMLTextAreaElement;
    expect(textbox.value).toBe("FLWs in rural Kenya");
  });

  it("saving the textbox calls onEdit with row_id and new value", () => {
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
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    fireEvent.click(screen.getByText("Who is the target population?"));
    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    const textbox = screen.getByRole("textbox");
    fireEvent.change(textbox, { target: { value: "FLWs in rural Tanzania" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(onEdit).toHaveBeenCalledWith("row-1", "FLWs in rural Tanzania");
  });

  it("shows an 'edited' badge and the effective value when row is in buffer", () => {
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
    expect(screen.getByText("FLWs in rural Tanzania")).toBeInTheDocument();
    expect(screen.getByText(/edited/i)).toBeInTheDocument();
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
    // Open panel + row
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    const rowButton = screen.getByText("Who is the target population?").closest("button")!;
    fireEvent.click(rowButton);
    // Enter edit mode and type a partial draft
    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "WIP draft" } });
    // Collapse the row
    fireEvent.click(rowButton);
    // Re-expand
    fireEvent.click(rowButton);
    // Edit mode should be off; textbox should not exist
    expect(screen.queryByRole("textbox")).toBeNull();
    // Edit button should be visible again (not Save/Cancel)
    expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument();
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
    fireEvent.click(screen.getByText("Decisions").closest("button")!);
    fireEvent.click(screen.getByText("FLWs in rural Tanzania"));
    fireEvent.click(screen.getByRole("button", { name: /revert/i }));
    expect(onRevert).toHaveBeenCalledWith("row-1");
  });
});
