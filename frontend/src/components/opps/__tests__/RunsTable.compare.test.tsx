import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RunSummary } from "@/api/types.ws";
import { RunsTable } from "../RunsTable";

const run = (run_id: string) =>
  ({ run_id, phase_states: [], phases_total: 8, last_actor_at: null }) as unknown as RunSummary;
const RUNS = [run("20260728-0705"), run("20260722-1341"), run("20260702-1456")];

describe("RunsTable — compare two runs", () => {
  it("offers no compare mode unless the page asks for it", () => {
    render(<RunsTable runs={RUNS} workspaceSlug="ws" oppSlug="o" />);
    expect(screen.queryByLabelText(/Compare run/)).not.toBeInTheDocument();
  });

  it("asks for two runs, then offers the comparison", () => {
    render(<RunsTable runs={RUNS} workspaceSlug="ws" oppSlug="o" onCompare={vi.fn()} />);
    expect(screen.getByText(/Tick two runs/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Compare run 20260728-0705"));
    expect(screen.getByText(/Tick one more/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Compare run 20260722-1341"));
    expect(screen.getByRole("button", { name: /Compare these runs/ })).toBeInTheDocument();
  });

  it("always passes the earlier run first, whatever order they were ticked", () => {
    const onCompare = vi.fn();
    render(<RunsTable runs={RUNS} workspaceSlug="ws" oppSlug="o" onCompare={onCompare} />);
    fireEvent.click(screen.getByLabelText("Compare run 20260728-0705"));
    fireEvent.click(screen.getByLabelText("Compare run 20260722-1341"));
    fireEvent.click(screen.getByRole("button", { name: /Compare these runs/ }));
    expect(onCompare).toHaveBeenCalledWith("20260722-1341", "20260728-0705");
  });

  it("a third tick replaces the oldest, so it's always the last two", () => {
    const onCompare = vi.fn();
    render(<RunsTable runs={RUNS} workspaceSlug="ws" oppSlug="o" onCompare={onCompare} />);
    fireEvent.click(screen.getByLabelText("Compare run 20260728-0705"));
    fireEvent.click(screen.getByLabelText("Compare run 20260722-1341"));
    fireEvent.click(screen.getByLabelText("Compare run 20260702-1456"));
    fireEvent.click(screen.getByRole("button", { name: /Compare these runs/ }));
    expect(onCompare).toHaveBeenCalledWith("20260702-1456", "20260722-1341");
  });
});
