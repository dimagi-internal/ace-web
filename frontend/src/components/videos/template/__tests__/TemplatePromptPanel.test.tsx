import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TemplatePromptPanel } from "../TemplatePromptPanel";
import type { TemplateEditorAction } from "../templateEditorReducer";
import type { Dispatch } from "react";

function renderPanel(promptMd = "# Initial prompt", dispatch: Dispatch<TemplateEditorAction> = vi.fn()) {
  return { dispatch, ...render(<TemplatePromptPanel promptMd={promptMd} dispatch={dispatch} />) };
}

describe("TemplatePromptPanel", () => {
  it("renders textarea prefilled with promptMd", () => {
    renderPanel();
    expect(screen.getByRole("textbox")).toHaveValue("# Initial prompt");
  });

  it("shows a Markdown hint label", () => {
    renderPanel();
    // The badge/hint span contains "Markdown" — getAllByText avoids the
    // "multiple elements" error since the label "Prompt" also exists nearby.
    const matches = screen.getAllByText(/Markdown/i);
    expect(matches.length).toBeGreaterThan(0);
  });

  it("typing dispatches set-prompt with the new value", () => {
    const { dispatch } = renderPanel();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "# Updated prompt" } });
    expect(dispatch).toHaveBeenCalledWith({ type: "set-prompt", value: "# Updated prompt" });
  });

  it("textarea is associated with a visible label", () => {
    renderPanel();
    // The label "Prompt" should be tied to the textarea via htmlFor/id
    expect(screen.getByLabelText(/prompt/i)).toBeInTheDocument();
  });
});
