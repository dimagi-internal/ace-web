import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TemplateSkeletonPanel } from "../TemplateSkeletonPanel";
import type { TemplateEditorAction } from "../templateEditorReducer";
import type { Dispatch } from "react";

const validYaml = "beats:\n  - id: hook\n    seconds: 8";
const tabYaml = "beats:\n\t- id: hook";
const unbalancedBracket = "items: [a, b";
const unbalancedBrace = "data: {x: 1";
const duplicateKey = "name: foo\nname: bar";

function renderPanel(
  skeletonYaml = validYaml,
  dispatch: Dispatch<TemplateEditorAction> = vi.fn(),
) {
  return { dispatch, ...render(<TemplateSkeletonPanel skeletonYaml={skeletonYaml} dispatch={dispatch} />) };
}

describe("TemplateSkeletonPanel", () => {
  it("renders textarea prefilled with skeletonYaml", () => {
    renderPanel();
    expect(screen.getByRole("textbox")).toHaveValue(validYaml);
  });

  it("typing dispatches set-skeleton with the new value", () => {
    const { dispatch } = renderPanel();
    const newYaml = "beats:\n  - id: intro\n    seconds: 10";
    fireEvent.change(screen.getByRole("textbox"), { target: { value: newYaml } });
    expect(dispatch).toHaveBeenCalledWith({ type: "set-skeleton", value: newYaml });
  });

  it("shows no error hint for valid YAML", () => {
    renderPanel(validYaml);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows error hint when YAML uses tabs for indentation", () => {
    renderPanel(tabYaml);
    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toMatch(/tab/i);
  });

  it("shows error hint for unbalanced square brackets", () => {
    renderPanel(unbalancedBracket);
    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toMatch(/bracket/i);
  });

  it("shows error hint for unbalanced curly braces", () => {
    renderPanel(unbalancedBrace);
    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toMatch(/brace/i);
  });

  it("shows error hint for duplicate mapping keys", () => {
    renderPanel(duplicateKey);
    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toMatch(/duplicate/i);
  });

  it("does NOT flag repeated keys across sibling list items (valid YAML)", () => {
    // product.beats — each "- asset:" begins a new list element, not a dup key.
    const listYaml =
      "product:\n  beats:\n    - asset: a\n      caption: x\n    - asset: b\n      caption: y";
    renderPanel(listYaml);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("still flags a genuine duplicate key WITHIN one list item", () => {
    const dupInItem = "beats:\n  - asset: a\n    asset: b";
    renderPanel(dupInItem);
    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toMatch(/duplicate/i);
  });

  it("shows no error for empty textarea", () => {
    renderPanel("");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("textarea has an accessible label", () => {
    renderPanel();
    expect(screen.getByLabelText(/skeleton yaml/i)).toBeInTheDocument();
  });
});
