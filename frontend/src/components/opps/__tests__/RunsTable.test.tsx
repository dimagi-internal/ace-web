import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { RunsTable } from "../RunsTable";
import type { RunSummary } from "@/api/types.ws";

function run(over: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: "20260813-2126",
    current_phase: null,
    current_step: null,
    mode: "default",
    last_actor: "a@b.c",
    last_actor_at: "2026-08-14T03:26:00Z",
    phases_total: 4,
    phases_done: 4,
    ...over,
  } as RunSummary;
}

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe("RunsTable", () => {
  it("draws one segment per phase and labels each with its status", () => {
    wrap(
      <RunsTable
        runs={[run({ phase_states: [
          { ordinal: 1, name: "idea-to-design", status: "done" },
          { ordinal: 2, name: "commcare-setup", status: "error" },
          { ordinal: 3, name: "closeout", status: "pending" },
        ] })]}
        workspaceSlug="ws"
        oppSlug="opp"
      />,
    );
    expect(screen.getByTitle("1 · idea-to-design — done")).toBeInTheDocument();
    expect(screen.getByTitle("2 · commcare-setup — error")).toBeInTheDocument();
    expect(screen.getByTitle("3 · closeout — pending")).toBeInTheDocument();
  });

  it("shows an errored mid-run phase that the done-count hides", () => {
    // phases_done says 4/4 (error is not a PENDING status server-side), so the
    // count alone reads as a clean run. The track must still show the break.
    const { container } = wrap(
      <RunsTable
        runs={[run({ phases_done: 4, phase_states: [
          { ordinal: 1, name: "a", status: "done" },
          { ordinal: 2, name: "b", status: "error" },
          { ordinal: 3, name: "c", status: "done" },
          { ordinal: 4, name: "d", status: "done" },
        ] })]}
        workspaceSlug="ws"
        oppSlug="opp"
      />,
    );
    expect(container.querySelectorAll(".bg-destructive").length).toBe(1);
  });

  it("falls back to plain segments when phase_states is absent (older payload)", () => {
    const { container } = wrap(
      <RunsTable runs={[run()]} workspaceSlug="ws" oppSlug="opp" />,
    );
    // 4 phases_total -> 4 segments, all 'not recorded'
    expect(container.querySelectorAll('[title="phase 1 — not recorded"]').length).toBe(1);
    // No cursor, nothing done, never dispatched -> "queued", which is the
    // honest label. (A run no runner can CLAIM says so instead; see
    // OppRunsList's execution-state tests.)
    expect(screen.getByText(/queued/)).toBeInTheDocument();
  });

  it("prefers the live step label over the last-done phase", () => {
    wrap(
      <RunsTable
        runs={[run({ current_step: "app-release", current_step_display: "App release" })]}
        workspaceSlug="ws"
        oppSlug="opp"
      />,
    );
    expect(screen.getByText("App release")).toBeInTheDocument();
  });

  it("calls onSelect instead of navigating when the workbench owns selection", () => {
    const onSelect = vi.fn();
    wrap(
      <RunsTable runs={[run()]} workspaceSlug="ws" oppSlug="opp" onSelect={onSelect} />,
    );
    fireEvent.click(screen.getByText("20260813-2126"));
    expect(onSelect).toHaveBeenCalledWith("20260813-2126");
  });

  it("expands to reveal deep links, including Drive when folder_id is served", () => {
    wrap(
      <RunsTable
        runs={[run({ folder_id: "FOLDER1" })]}
        workspaceSlug="ws"
        oppSlug="opp"
      />,
    );
    expect(screen.queryByText(/Drive run folder/)).toBeNull();
    fireEvent.click(screen.getByLabelText("Expand 20260813-2126"));
    expect(screen.getByText(/Drive run folder/).closest("a")).toHaveAttribute(
      "href",
      "https://drive.google.com/drive/folders/FOLDER1",
    );
    expect(screen.getByText(/run summary/).closest("a")).toHaveAttribute(
      "href",
      "/ace/opps/ws/opp/runs/20260813-2126/summary",
    );
  });

  it("omits the Drive link when folder_id was not served", () => {
    wrap(<RunsTable runs={[run()]} workspaceSlug="ws" oppSlug="opp" />);
    fireEvent.click(screen.getByLabelText("Expand 20260813-2126"));
    expect(screen.queryByText(/Drive run folder/)).toBeNull();
  });

  it("renders nothing for an opp with no runs", () => {
    const { container } = wrap(
      <RunsTable runs={[]} workspaceSlug="ws" oppSlug="opp" />,
    );
    expect(container.firstChild).toBeNull();
  });
});
