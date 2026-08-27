import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { RunsTable } from "../RunsTable";
import type { RunSummary } from "@/api/types.ws";

const run = {
  run_id: "20260813-2126",
  current_phase: null,
  current_step: null,
  mode: "default",
  last_actor: null,
  last_actor_at: "2026-08-14T03:26:00Z",
  phases_total: 3,
  phases_done: 2,
  phase_states: [
    { ordinal: 1, name: "idea-to-design", status: "done" },
    { ordinal: 2, name: "commcare-setup", status: "error" },
  ],
} as RunSummary;

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe("RunsTable — phase click-through", () => {
  it("opens that phase for that run", () => {
    const onOpenPhase = vi.fn();
    wrap(
      <RunsTable runs={[run]} workspaceSlug="ws" oppSlug="opp" onOpenPhase={onOpenPhase} />,
    );
    fireEvent.click(screen.getByLabelText("Open commcare-setup for run 20260813-2126"));
    expect(onOpenPhase).toHaveBeenCalledWith("20260813-2126", "commcare-setup");
  });

  it("a phase the run never reached is NOT navigable", () => {
    // Landing on a phase with no data reads as a broken page rather than as
    // "this run stopped before here".
    const onOpenPhase = vi.fn();
    const { container } = wrap(
      <RunsTable runs={[run]} workspaceSlug="ws" oppSlug="opp" onOpenPhase={onOpenPhase} />,
    );
    // 3 phases_total, only 2 recorded -> exactly 2 buttons in the track.
    const buttons = container.querySelectorAll('button[aria-label^="Open "]');
    expect(buttons).toHaveLength(2);
  });

  it("segments stay inert when no handler is supplied", () => {
    const { container } = wrap(<RunsTable runs={[run]} workspaceSlug="ws" oppSlug="opp" />);
    expect(container.querySelectorAll('button[aria-label^="Open "]')).toHaveLength(0);
  });

  it("clicking a phase does not also fire the row's run-select", () => {
    const onSelect = vi.fn();
    const onOpenPhase = vi.fn();
    wrap(
      <RunsTable
        runs={[run]} workspaceSlug="ws" oppSlug="opp"
        onSelect={onSelect} onOpenPhase={onOpenPhase}
      />,
    );
    fireEvent.click(screen.getByLabelText("Open idea-to-design for run 20260813-2126"));
    expect(onOpenPhase).toHaveBeenCalled();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
