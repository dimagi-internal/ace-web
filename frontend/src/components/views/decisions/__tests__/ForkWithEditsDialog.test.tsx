import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import type { ComponentProps } from "react";

import type { PhaseInfo } from "@/api/types.ws";
import { ForkWithEditsDialog } from "../ForkWithEditsDialog";

type DialogProps = ComponentProps<typeof ForkWithEditsDialog>;

const phases: PhaseInfo[] = [
  { name: "design", ordinal: 1, display_name: "Design" } as PhaseInfo,
  { name: "scenarios-and-acceptance", ordinal: 2, display_name: "Scenarios" } as PhaseInfo,
];

const baseProps: DialogProps = {
  open: true,
  onClose: vi.fn(),
  workspaceSlug: "dimagi",
  sourceSlug: "test-opp",
  sourceRunId: "20260101-1000",
  initialForkAtPhase: "design",
  phases,
  edits: [{ row_id: "a", new_answer: "v2" }],
  affectedDocs: ["1-design/idea-to-pdd.md", "1-design/pdd-to-work-order.gdoc"],
};

function renderDialog(props: DialogProps = baseProps) {
  return render(
    <MemoryRouter>
      <ForkWithEditsDialog {...props} />
    </MemoryRouter>,
  );
}

describe("ForkWithEditsDialog", () => {
  it("shows the affected docs list", () => {
    renderDialog();
    expect(screen.getByText("1-design/idea-to-pdd.md")).toBeInTheDocument();
    expect(screen.getByText("1-design/pdd-to-work-order.gdoc")).toBeInTheDocument();
  });

  it("shows a fallback message when affected docs is empty", () => {
    renderDialog({ ...baseProps, affectedDocs: [] });
    expect(screen.getByText(/will regenerate this phase's outputs/i)).toBeInTheDocument();
  });

  it("defaults fork point to initialForkAtPhase prop", () => {
    renderDialog();
    const select = screen.getByLabelText(/fork point/i) as HTMLSelectElement;
    expect(select.value).toBe("design");
  });

  it("Cancel calls onClose", () => {
    const onClose = vi.fn();
    renderDialog({ ...baseProps, onClose });
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("Fork & re-run posts edits to the API with keep-overrides-only as default", async () => {
    const forkSpy = vi.fn().mockResolvedValue({
      slug: "test-opp",
      run_id: "20260522-1500",
      working_session_slug: "abc",
    });
    renderDialog({ ...baseProps, __forkOppForTest: forkSpy });
    fireEvent.click(screen.getByRole("button", { name: /fork & re-run/i }));
    await waitFor(() => expect(forkSpy).toHaveBeenCalled());
    expect(forkSpy).toHaveBeenCalledWith("dimagi", "test-opp", {
      fork_at_phase: "design",
      source_run_id: "20260101-1000",
      edits: [{ row_id: "a", new_answer: "v2" }],
      mode: "keep-overrides-only",
    });
  });

  it("switching to keep-all sends mode=keep-all", async () => {
    const forkSpy = vi.fn().mockResolvedValue({
      slug: "test-opp",
      run_id: "20260522-1500",
      working_session_slug: "abc",
    });
    renderDialog({ ...baseProps, __forkOppForTest: forkSpy });
    // Click the "Keep all decisions" radio.
    fireEvent.click(screen.getByRole("radio", { name: /keep all decisions/i }));
    fireEvent.click(screen.getByRole("button", { name: /fork & re-run/i }));
    await waitFor(() => expect(forkSpy).toHaveBeenCalled());
    expect(forkSpy.mock.calls[0][2]).toMatchObject({ mode: "keep-all" });
  });
});
