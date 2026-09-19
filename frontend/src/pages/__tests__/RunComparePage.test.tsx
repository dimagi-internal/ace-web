import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RunCompare } from "@/api/runCompare";

const fetchRunCompare = vi.fn();
vi.mock("@/api/runCompare", async (orig) => ({
  ...(await orig<typeof import("@/api/runCompare")>()),
  fetchRunCompare: (...a: unknown[]) => fetchRunCompare(...a),
}));
const { default: RunComparePage } = await import("../RunComparePage");

const header = (run_id: string) =>
  ({ run_id, started_at: null, completed_at: null, steps_run: 40, decision_count: 30 });
const DATA: RunCompare = {
  schema_version: 1,
  opp_slug: "hh",
  opp_title: "Household poverty targeting",
  base: header("20260722-1341"),
  head: header("20260728-0705"),
  new_decisions: [
    { id: "gps-capture-scope", phase: "design", phase_display: "Design", skill: null,
      question: "Which visit outcomes capture a GPS fix?", answer: "Every outcome", overridden: false },
  ],
  changed_decisions: [
    { id: "dedup", phase: "design", phase_display: "Design", skill: null,
      question: "What identifies a household for dedup?", answer: "Settlement code",
      overridden: false, before: "Same GPS point (<15m)", after: "Settlement code" },
  ],
  dropped_decisions: [],
  new_steps: [{ skill: "app-connect-coverage", display_name: "App connect coverage",
                phase: "commcare", phase_display: "CommCare setup" }],
  dropped_steps: [],
  steps: [
    { skill: "learn-app-eval", display_name: "Learn app eval", phase: "commcare",
      phase_display: "CommCare setup", ordinal: 1, changed: true,
      base: { label: "passed", status: "done", score: null },
      head: { label: "did not pass", status: "done", score: null } },
  ],
};

function renderAt(q = "?base=20260722-1341&head=20260728-0705") {
  return render(
    <MemoryRouter initialEntries={[`/w/ws/opps/hh/compare${q}`]}>
      <Routes>
        <Route path="/w/:workspaceSlug/opps/:slug/compare" element={<RunComparePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RunComparePage", () => {
  beforeEach(() => {
    fetchRunCompare.mockReset();
    fetchRunCompare.mockResolvedValue(DATA);
  });

  it("asks the server for the two runs in the URL", async () => {
    renderAt();
    await screen.findByText("What the later run did differently");
    expect(fetchRunCompare).toHaveBeenCalledWith("ws", "hh", "20260722-1341", "20260728-0705");
  });

  it("leads with what's new, not scores", async () => {
    renderAt();
    expect(await screen.findByText("Which visit outcomes capture a GPS fix?")).toBeInTheDocument();
    expect(screen.getByText("Every outcome")).toBeInTheDocument();
    expect(screen.getByText("App connect coverage")).toBeInTheDocument();
  });

  it("shows a changed answer as before and after", async () => {
    renderAt();
    expect(await screen.findByText("Same GPS point (<15m)")).toBeInTheDocument();
    expect(screen.getAllByText("Settlement code").length).toBeGreaterThan(0);
  });

  it("states verdicts plainly, with no better/worse arrows", async () => {
    const { container } = renderAt();
    await screen.findByText("What the later run did differently");
    expect(container.textContent).toContain("did not pass");
    expect(container.textContent).not.toMatch(/[↑↓▲▼]/);
  });

  it("explains a missing run rather than showing an empty page", async () => {
    fetchRunCompare.mockRejectedValue(new Error("One of those runs couldn't be found."));
    renderAt();
    expect(await screen.findByText("One of those runs couldn't be found.")).toBeInTheDocument();
  });
});
