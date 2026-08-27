import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TemplateExamplePanel } from "../TemplateExamplePanel";

const validYaml = "beats:\n  - id: hook\n    seconds: 8";
const tabYaml = "beats:\n\t- id: hook";
const unbalancedBracket = "items: [a, b";
const unbalancedBrace = "data: {x: 1";
const duplicateKey = "name: foo\nname: bar";

function renderPanel(exampleYaml = validYaml) {
  return render(<TemplateExamplePanel exampleYaml={exampleYaml} />);
}

describe("TemplateExamplePanel", () => {
  it("renders textarea prefilled with exampleYaml", () => {
    renderPanel();
    expect(screen.getByRole("textbox")).toHaveValue(validYaml);
  });

  it("textarea has an accessible label", () => {
    renderPanel();
    expect(screen.getByLabelText(/example yaml/i)).toBeInTheDocument();
  });

  it("is a read-only reference (not editable)", () => {
    renderPanel();
    expect(screen.getByRole("textbox")).toHaveAttribute("readonly");
  });

  it("shows no error hint for valid YAML", () => {
    renderPanel(validYaml);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows no error for empty textarea", () => {
    renderPanel("");
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
});
