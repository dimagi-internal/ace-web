import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { NarrationPanel } from "../drawer/panels/NarrationPanel";
import { BeatEditorProvider } from "../BeatEditorContext";
import type { ProgramSpec } from "../types";

const spec: ProgramSpec = {
  slug: "demo", name: "Demo",
  narration: { by_beat: { hook: "Initial text" } },
};

function renderPanel(onCommit = vi.fn(), onCancel = vi.fn()) {
  return render(
    <BeatEditorProvider workspaceSlug="ws1" programSlug="demo" runId="run-001" spec={spec}>
      <NarrationPanel beatId="hook" onCommit={onCommit} onCancel={onCancel} />
    </BeatEditorProvider>,
  );
}

describe("NarrationPanel", () => {
  it("prefills the textarea with current text", () => {
    renderPanel();
    expect(screen.getByRole("textbox")).toHaveValue("Initial text");
  });

  it("Done is disabled when text is unchanged", () => {
    renderPanel();
    expect(screen.getByRole("button", { name: /Done/i })).toBeDisabled();
  });

  it("typing enables Done", () => {
    renderPanel();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "New text" } });
    expect(screen.getByRole("button", { name: /Done/i })).toBeEnabled();
  });

  it("clicking Done calls onCommit", () => {
    const onCommit = vi.fn();
    renderPanel(onCommit);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "New text" } });
    fireEvent.click(screen.getByRole("button", { name: /Done/i }));
    expect(onCommit).toHaveBeenCalled();
  });

  it("Cmd+Enter submits", () => {
    const onCommit = vi.fn();
    renderPanel(onCommit);
    const ta = screen.getByRole("textbox");
    fireEvent.change(ta, { target: { value: "New text" } });
    fireEvent.keyDown(ta, { key: "Enter", metaKey: true });
    expect(onCommit).toHaveBeenCalled();
  });
});
