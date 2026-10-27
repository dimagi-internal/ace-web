import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { RunsTable } from "../RunsTable";
import type { RunSummary } from "@/api/types.ws";

const run = {
  run_id: "20261012-1549",
  last_actor_at: "2026-10-12T19:49:00Z",
  phases_total: 1,
  phases_done: 1,
  phase_states: [{ ordinal: 1, name: "idea-to-design", status: "done" }],
} as RunSummary;

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe("RunsTable — archive", () => {
  it("offers Archive in the expanded row and reports the run id", () => {
    const onArchive = vi.fn();
    wrap(<RunsTable runs={[run]} workspaceSlug="ws" oppSlug="opp" onArchive={onArchive} />);
    fireEvent.click(screen.getByLabelText("Expand 20261012-1549"));
    fireEvent.click(screen.getByRole("button", { name: /archive/i }));
    expect(onArchive).toHaveBeenCalledWith("20261012-1549");
  });

  it("shows no Archive button when no handler is supplied", () => {
    wrap(<RunsTable runs={[run]} workspaceSlug="ws" oppSlug="opp" />);
    fireEvent.click(screen.getByLabelText("Expand 20261012-1549"));
    expect(screen.queryByRole("button", { name: /archive/i })).toBeNull();
  });
});
