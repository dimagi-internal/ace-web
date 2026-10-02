/**
 * Step deep links after the Workbench tab was retired: every `/steps/<skill>`
 * address lands on Phases with that step's detail open — whatever `?view=` it
 * carries (old links said `?view=workbench`) — and the page builds/clears
 * those addresses for PhaseView.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
vi.mock("../../components/opps/WorkbenchHeader", () => ({ WorkbenchHeader: () => null }));
vi.mock("../../components/opps/RunsTable", () => ({
  RunsTable: () => <div data-testid="runs-table" />,
}));
vi.mock("../../components/opps/ForkOppDialog", () => ({ ForkOppDialog: () => null }));
vi.mock("@/components/opps/ClonedToBanner", () => ({ ClonedToBanner: () => null }));

interface PhaseProps {
  openSkill: string | null;
  stepHref: (skill: string, phase: string) => string;
  onCloseStep: (phase?: string) => void;
}
let phaseProps: PhaseProps | null = null;
vi.mock("../../components/views/PhaseView", () => ({
  PhaseView: (p: PhaseProps) => {
    phaseProps = p;
    return <div data-testid="phase-view" data-open={p.openSkill ?? ""} />;
  },
}));

const { default: OppRunPage } = await import("../OppRunPage");

const RUN = "20260926-1413";
const SNAPSHOT = {
  opp: { slug: "opp", display_name: "Opp" },
  pdd_body: "",
  runs: [{ run_id: RUN, last_actor_at: null }],
  selected_run_id: RUN,
  phases: [],
  current_run: {
    run_id: RUN, mode: "auto", status: "complete", started_at: null,
    completed_at: null, current_phase: null, current_step: null, skill_versions: {},
    notes: "", steps: [], decisions: [],
  },
};

let location = { pathname: "", search: "" };
function LocationProbe() {
  const l = useLocation();
  location = { pathname: l.pathname, search: l.search };
  return null;
}

function renderAt(url: string) {
  const page = (
    <>
      <OppRunPage />
      <LocationProbe />
    </>
  );
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/w/:workspaceSlug/opps/:slug" element={page} />
        <Route path="/w/:workspaceSlug/opps/:slug/runs/:runId" element={page} />
        <Route path="/w/:workspaceSlug/opps/:slug/runs/:runId/steps/:skill" element={page} />
        <Route path="/w/:workspaceSlug/opps/:slug/steps/:skill" element={page} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  getOpp.mockReset();
  getOpp.mockResolvedValue(SNAPSHOT);
  phaseProps = null;
});

describe("OppRunPage step deep links", () => {
  it("has no Workbench tab — Phases and Runs only", async () => {
    renderAt(`/w/ws/opps/opp/runs/${RUN}`);
    await screen.findByTestId("phase-view");
    expect(screen.getByRole("button", { name: /Phases/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Runs/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Workbench/ })).not.toBeInTheDocument();
  });

  it("opens an old ?view=workbench step link on Phases with the step open", async () => {
    renderAt(`/w/ws/opps/opp/runs/${RUN}/steps/idea-to-pdd?view=workbench`);
    const view = await screen.findByTestId("phase-view");
    expect(view).toHaveAttribute("data-open", "idea-to-pdd");
    expect(getOpp.mock.calls[0][2]).toBe(RUN);
  });

  it("opens a run-less step link on the latest run", async () => {
    renderAt("/w/ws/opps/opp/steps/pdd-to-learn-app");
    const view = await screen.findByTestId("phase-view");
    expect(view).toHaveAttribute("data-open", "pdd-to-learn-app");
    expect(getOpp.mock.calls[0][2]).toBeUndefined();
  });

  it("opens no step on a plain run address", async () => {
    renderAt(`/w/ws/opps/opp/runs/${RUN}`);
    expect(await screen.findByTestId("phase-view")).toHaveAttribute("data-open", "");
  });

  it("builds step addresses under the loaded run, keeping the query minus view", async () => {
    renderAt(`/w/ws/opps/opp?run_id=${RUN}&view=phase`);
    await screen.findByTestId("phase-view");
    expect(phaseProps!.stepHref("idea to pdd", "idea-to-design")).toBe(
      `/w/ws/opps/opp/runs/${RUN}/steps/idea%20to%20pdd?run_id=${RUN}&phase=idea-to-design`,
    );
  });

  it("closing the step returns to the run address, on the phase asked for", async () => {
    renderAt(`/w/ws/opps/opp/runs/${RUN}/steps/idea-to-pdd?phase=idea-to-design`);
    await screen.findByTestId("phase-view");
    act(() => phaseProps!.onCloseStep("commcare-setup"));
    await waitFor(() => expect(location.pathname).toBe(`/w/ws/opps/opp/runs/${RUN}`));
    expect(location.search).toBe("?phase=commcare-setup");
    expect(screen.getByTestId("phase-view")).toHaveAttribute("data-open", "");
    // Same page instance: closing a step does not refetch the run.
    expect(getOpp).toHaveBeenCalledTimes(1);
  });

  it("switching to Runs from a step address drops the step from the path", async () => {
    renderAt(`/w/ws/opps/opp/runs/${RUN}/steps/idea-to-pdd`);
    await screen.findByTestId("phase-view");
    fireEvent.click(screen.getByRole("button", { name: /Runs/ }));
    await screen.findByTestId("runs-table");
    expect(location.pathname).toBe(`/w/ws/opps/opp/runs/${RUN}`);
    expect(location.search).toBe("?view=runs");
  });
});
