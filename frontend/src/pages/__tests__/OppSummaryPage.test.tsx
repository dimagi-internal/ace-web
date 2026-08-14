import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api/oppSummary";
import type { OppSummaryPayload } from "@/api/oppSummary";
import OppSummaryPage from "@/pages/OppSummaryPage";

const BASE: OppSummaryPayload = {
  opp: {
    workspace_slug: "dimagi-team",
    slug: "spark-facilitator",
    run_id: "20260813-2126",
    display_name: "Spark Facilitator",
    description: "Verified community-meeting facilitation.",
    status: "active",
    end_date: "2027-03-14",
  },
  design: {
    docs: [{ title: "Program Design Document", url: "https://docs/pdd" }],
  },
  apps: [],
  connect: null,
  training: null,
  assistant: null,
  walkthroughs: [],
  dashboards: [],
  selected_llo: null,
  solicitation: null,
  launch: null,
  cycle_grade: null,
  opp_eval: null,
  learnings: null,
  open_questions: null,
  feedback: [],
  stage: null,
  workbench_url: null,
};

function renderWith(payload: OppSummaryPayload) {
  vi.spyOn(api, "getPublicOppSummary").mockResolvedValue(payload);
  return render(
    <MemoryRouter initialEntries={["/ace/opps/dimagi-team/spark-facilitator/runs/20260813-2126/summary"]}>
      <Routes>
        <Route
          path="/ace/opps/:workspace/:slug/runs/:runId/summary"
          element={<OppSummaryPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("OppSummaryPage", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("links the design docs a reviewer is meant to comment on", async () => {
    renderWith(BASE);
    expect(await screen.findByText("Program Design Document")).toBeTruthy();
  });

  it("says a withheld walkthrough was withheld, not that it doesn't exist", async () => {
    renderWith({
      ...BASE,
      walkthroughs: [{
        persona: "Walkthrough",
        url: null,
        eval_score: null,
        availability: "withheld",
        withheld_reason: "Not shown — did not pass quality review",
      }],
    });
    expect(
      await screen.findByText(/did not pass quality review/),
    ).toBeTruthy();
    expect(screen.queryByText("Open deck")).toBeNull();
  });

  it("distinguishes 'not started yet' from 'Not created'", async () => {
    renderWith({
      ...BASE,
      stage: { label: "solicitation", pending_sections: ["selected_llo", "launch"] },
    });
    const notStarted = await screen.findAllByText(
      "Not started — this run is at the solicitation stage",
    );
    // LLO + Live rows.
    expect(notStarted.length).toBe(2);
    // Sections whose phase HAS run keep the plain missing state.
    expect(screen.getAllByText("Not created").length).toBeGreaterThan(0);
  });

  it("hides the Workbench link when the payload has none (public visitor)", async () => {
    renderWith(BASE);
    await screen.findAllByText("Spark Facilitator");
    expect(screen.queryByText(/See the full build process/)).toBeNull();
  });

  it("shows the Workbench link for a member payload", async () => {
    renderWith({ ...BASE, workbench_url: "/w/dimagi-team/opps/spark-facilitator/runs/20260813-2126" });
    expect(await screen.findByText(/See the full build process/)).toBeTruthy();
  });

  it("renders dashboards when the payload carries them", async () => {
    renderWith({
      ...BASE,
      dashboards: [{ title: "LLO weekly", url: "https://labs/one" }],
    });
    expect(await screen.findByText("LLO weekly")).toBeTruthy();
  });
});
