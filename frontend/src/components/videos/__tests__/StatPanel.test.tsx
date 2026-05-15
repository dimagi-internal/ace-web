import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { StatPanel } from "../drawer/panels/StatPanel";
import { BeatEditorProvider } from "../BeatEditorContext";
import type { ProgramSpec } from "../types";

const spec: ProgramSpec = {
  slug: "demo", name: "Demo",
  narration: { by_beat: {} },
  problem: { big: "29%", caption: "old caption", source: "NDHS 2018" },
  impact: [{ big: "$1", caption: "a" }],
};

function renderPanel(path: string, onCommit = vi.fn(), onCancel = vi.fn()) {
  return render(
    <BeatEditorProvider workspaceSlug="ws1" programSlug="demo" runId="run-001" spec={spec}>
      <StatPanel path={path} onCommit={onCommit} onCancel={onCancel} />
    </BeatEditorProvider>,
  );
}

describe("StatPanel", () => {
  it("prefills problem fields", () => {
    renderPanel("problem");
    expect(screen.getByLabelText(/big/i)).toHaveValue("29%");
    expect(screen.getByLabelText(/caption/i)).toHaveValue("old caption");
  });

  it("Done is disabled until a field changes", () => {
    renderPanel("problem");
    expect(screen.getByRole("button", { name: /Done/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/big/i), { target: { value: "31%" } });
    expect(screen.getByRole("button", { name: /Done/i })).toBeEnabled();
  });

  it("clicking Done calls onCommit", () => {
    const onCommit = vi.fn();
    renderPanel("problem", onCommit);
    fireEvent.change(screen.getByLabelText(/big/i), { target: { value: "31%" } });
    fireEvent.click(screen.getByRole("button", { name: /Done/i }));
    expect(onCommit).toHaveBeenCalled();
  });

  it("Clear source removes source from output op", () => {
    renderPanel("problem");
    fireEvent.click(screen.getByRole("button", { name: /clear source/i }));
    expect(screen.getByLabelText(/source/i)).toHaveValue("");
  });
});
