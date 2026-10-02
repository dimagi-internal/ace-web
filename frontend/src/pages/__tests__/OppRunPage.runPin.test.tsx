import { render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Only the page's own fetch/URL logic is under test; every child that
// renders the snapshot or opens a socket is stubbed.
const getOpp = vi.fn();
vi.mock("../../api/opps", () => ({ getOpp: (...a: unknown[]) => getOpp(...a) }));
vi.mock("../../api/oppCache", () => ({ dropOpp: vi.fn() }));
vi.mock("../../hooks/useOppSocket", () => ({
  useOppSocket: () => ({ sendDecisionEdit: vi.fn(), sendDecisionRevert: vi.fn() }),
}));
vi.mock("../../hooks/useOppCostRollup", () => ({ useOppCostRollup: () => null }));
vi.mock("../../components/replay/useReplay", () => ({
  useReplay: () => ({ active: false, start: vi.fn() }),
}));
vi.mock("../../components/views/PhaseView", () => ({ PhaseView: () => null }));
vi.mock("../../components/opps/WorkbenchHeader", () => ({ WorkbenchHeader: () => null }));
vi.mock("../../components/opps/RunsTable", () => ({ RunsTable: () => null }));
vi.mock("../../components/opps/ForkOppDialog", () => ({ ForkOppDialog: () => null }));
vi.mock("@/components/opps/ClonedToBanner", () => ({ ClonedToBanner: () => null }));

const { default: OppRunPage } = await import("../OppRunPage");

const SNAPSHOT = {
  opp: { slug: "opp", display_name: "Opp" },
  pdd_body: "",
  runs: [{ run_id: "20260926-1413", last_actor_at: null }],
  selected_run_id: "20260926-1413",
  phases: [],
  current_run: {
    run_id: "20260926-1413", mode: "auto", status: "complete", started_at: null,
    completed_at: null, current_phase: null, current_step: null, skill_versions: {},
    notes: "", steps: [], decisions: [],
  },
};

let search = "";
function LocationProbe() {
  search = useLocation().search;
  return null;
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route
          path="/w/:workspaceSlug/opps/:slug"
          element={<><OppRunPage /><LocationProbe /></>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("OppRunPage run-id pinning", () => {
  beforeEach(() => {
    getOpp.mockReset();
    getOpp.mockResolvedValue(SNAPSHOT);
    search = "";
  });

  it("pins the loaded run into the URL without fetching it a second time", async () => {
    renderAt("/w/ws/opps/opp");

    await waitFor(() => expect(search).toContain("run_id=20260926-1413"));
    // Give a refetch (had one been triggered by the URL change) a chance to fire.
    await new Promise((r) => setTimeout(r, 20));
    expect(getOpp).toHaveBeenCalledTimes(1);
    expect(getOpp.mock.calls[0][2]).toBeUndefined();
  });

  it("fetches exactly the run a shared link names", async () => {
    renderAt("/w/ws/opps/opp?run_id=20260901-0900");

    await waitFor(() => expect(getOpp).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(getOpp).toHaveBeenCalledTimes(1);
    expect(getOpp.mock.calls[0][2]).toBe("20260901-0900");
  });
});
