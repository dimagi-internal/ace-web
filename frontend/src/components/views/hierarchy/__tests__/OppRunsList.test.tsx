import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RunSummary } from "@/api/types.ws";

const runs = vi.hoisted(() => ({ value: [] as RunSummary[] | null }));

vi.mock("@/hooks/useOppRuns", () => ({
  useOppRuns: () => runs.value,
}));

import { OppRunsList } from "../OppRunsList";

function _run(over: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: "20260726-1200",
    current_phase: null,
    current_step: null,
    mode: null,
    last_actor: null,
    last_actor_at: null,
    ...over,
  };
}

function _render() {
  return render(
    <MemoryRouter>
      <OppRunsList oppSlug="opp-a" workspaceSlug="ws1" />
    </MemoryRouter>,
  );
}

describe("OppRunsList — a run nothing can execute", () => {
  beforeEach(() => {
    runs.value = [];
  });

  it("stops calling an unclaimable run 'queued'", () => {
    // The defect: "about to start" and "no runner will ever take this" both
    // rendered as the literal string "queued".
    runs.value = [
      _run({
        execution: {
          state: "no_runner_configured",
          detail: "no runner can take this session",
          canopy_turn_id: "turn-1",
          canopy_session_id: "sess-1",
        },
      }),
    ];
    _render();
    expect(screen.getByText(/no runner available/i)).toBeInTheDocument();
    expect(screen.queryByText(/^queued$/)).toBeNull();
  });

  it("still says 'queued' for a run that never went to canopy", () => {
    runs.value = [_run()];
    _render();
    expect(screen.getByText(/^queued$/)).toBeInTheDocument();
  });

  it("treats an explicitly not_dispatched run as the legacy local path", () => {
    runs.value = [
      _run({
        execution: {
          state: "not_dispatched",
          detail: "",
          canopy_turn_id: "",
          canopy_session_id: "",
        },
      }),
    ];
    _render();
    expect(screen.getByText(/^queued$/)).toBeInTheDocument();
  });

  it("does not let the execution badge override a live phase cursor", () => {
    // The badge is the fallback for "nothing done yet", not a replacement for
    // the run's real progress once it has some.
    runs.value = [
      _run({
        current_phase: "idea-to-design",
        current_phase_display: "Idea to design",
        execution: {
          state: "no_runner_configured",
          detail: "",
          canopy_turn_id: "t",
          canopy_session_id: "s",
        },
      }),
    ];
    _render();
    expect(screen.getByText("Idea to design")).toBeInTheDocument();
    expect(screen.queryByText(/no runner available/i)).toBeNull();
  });
});
