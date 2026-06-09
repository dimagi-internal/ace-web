import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TemplateMetaPanel } from "../TemplateMetaPanel";
import type { TemplateMeta } from "@/api/videos";
import type { TemplateEditorAction } from "../templateEditorReducer";
import type { Dispatch } from "react";

const meta: TemplateMeta = {
  id: "tpl-001",
  name: "Base Name",
  description: "Base description",
  intent: "Explain the mechanism in one breath.",
  expected_duration_seconds: 60,
  intended_audience: "CHW supervisors",
  when_to_use: "Onboarding",
};

function renderPanel(dispatch: Dispatch<TemplateEditorAction> = vi.fn()) {
  return { dispatch, ...render(<TemplateMetaPanel meta={meta} dispatch={dispatch} />) };
}

describe("TemplateMetaPanel", () => {
  it("renders all six fields prefilled from meta", () => {
    renderPanel();
    expect(screen.getByLabelText(/name/i)).toHaveValue("Base Name");
    expect(screen.getByLabelText(/intent/i)).toHaveValue("Explain the mechanism in one breath.");
    expect(screen.getByLabelText(/description/i)).toHaveValue("Base description");
    expect(screen.getByLabelText(/expected duration/i)).toHaveValue(60);
    expect(screen.getByLabelText(/intended audience/i)).toHaveValue("CHW supervisors");
    expect(screen.getByLabelText(/when to use/i)).toHaveValue("Onboarding");
  });

  it("changing intent dispatches set-meta-field with field=intent", () => {
    const { dispatch } = renderPanel();
    fireEvent.change(screen.getByLabelText(/intent/i), { target: { value: "New intent." } });
    expect(dispatch).toHaveBeenCalledWith({
      type: "set-meta-field",
      field: "intent",
      value: "New intent.",
    });
  });

  it("changing name dispatches set-meta-field with field=name", () => {
    const { dispatch } = renderPanel();
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: "New Name" } });
    expect(dispatch).toHaveBeenCalledWith({
      type: "set-meta-field",
      field: "name",
      value: "New Name",
    });
  });

  it("changing description dispatches set-meta-field with field=description", () => {
    const { dispatch } = renderPanel();
    fireEvent.change(screen.getByLabelText(/description/i), { target: { value: "Updated desc" } });
    expect(dispatch).toHaveBeenCalledWith({
      type: "set-meta-field",
      field: "description",
      value: "Updated desc",
    });
  });

  it("changing expected_duration_seconds dispatches a number value", () => {
    const { dispatch } = renderPanel();
    fireEvent.change(screen.getByLabelText(/expected duration/i), { target: { value: "120" } });
    expect(dispatch).toHaveBeenCalledWith({
      type: "set-meta-field",
      field: "expected_duration_seconds",
      value: 120,
    });
  });

  it("changing intended_audience dispatches set-meta-field with field=intended_audience", () => {
    const { dispatch } = renderPanel();
    fireEvent.change(screen.getByLabelText(/intended audience/i), { target: { value: "Nurses" } });
    expect(dispatch).toHaveBeenCalledWith({
      type: "set-meta-field",
      field: "intended_audience",
      value: "Nurses",
    });
  });

  it("changing when_to_use dispatches set-meta-field with field=when_to_use", () => {
    const { dispatch } = renderPanel();
    fireEvent.change(screen.getByLabelText(/when to use/i), { target: { value: "Before a campaign" } });
    expect(dispatch).toHaveBeenCalledWith({
      type: "set-meta-field",
      field: "when_to_use",
      value: "Before a campaign",
    });
  });
});
