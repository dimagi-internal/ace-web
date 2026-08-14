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
    docs: [
      { title: "Program Design Document", url: "https://docs/pdd", access: "public" },
    ],
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
  decisions: null,
  feedback: [],
  stage: null,
  workbench: null,
  viewer: { is_member: false },
};

const DECISION = {
  id: "row",
  phase: "idea-to-design",
  phase_raw: "1-design",
  phase_label: "Design",
  phase_ordinal: 1,
  skill: "idea-to-pdd",
  question: "A question",
  ai_default: "the pick",
  override: "",
  options_considered: ["the pick", "the other one"],
  source: "PDD § 2",
  status: "ai-default",
  notes: "because",
  override_reasoning: "",
  evidence_basis: "stated",
  conflict_signals: [],
} satisfies NonNullable<OppSummaryPayload["decisions"]>["rows"][number];

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

  it("shows the Workbench link to an anonymous visitor, tagged admin only", async () => {
    // Hiding it (the previous behaviour) reads to an outsider exactly
    // like the run not existing. Jonathan, 2026-08-14: show the link,
    // tag it.
    renderWith({
      ...BASE,
      workbench: {
        url: "/w/dimagi-team/opps/spark-facilitator/runs/20260813-2126",
        access: "admin",
      },
    });
    expect(await screen.findByText(/See the full build process/)).toBeTruthy();
    expect(screen.getAllByText("admin only").length).toBe(1);
  });

  it("drops the admin-only tags for a workspace member", async () => {
    renderWith({
      ...BASE,
      viewer: { is_member: true },
      workbench: {
        url: "/w/dimagi-team/opps/spark-facilitator/runs/20260813-2126",
        access: "admin",
      },
      dashboards: [{ title: "LLO weekly", url: "https://labs/one", access: "admin" }],
    });
    expect(await screen.findByText("LLO weekly")).toBeTruthy();
    expect(screen.queryByText("admin only")).toBeNull();
  });

  it("renders dashboards when the payload carries them, tagged admin only", async () => {
    renderWith({
      ...BASE,
      dashboards: [{ title: "LLO weekly", url: "https://labs/one", access: "admin" }],
    });
    expect(await screen.findByText("LLO weekly")).toBeTruthy();
    expect(screen.getAllByText("admin only").length).toBe(1);
  });

  it("renders open questions as content, not just a link to a doc nobody can open", async () => {
    renderWith({
      ...BASE,
      open_questions: {
        url: "https://docs/open-questions",
        access: "admin",
        items: [{
          title: "Rate confirmation",
          detail: "the USD 2-5 band is ACE-inferred",
          owner: "responding LLO + Spark",
          answered_in: "solicitation response (Phase 8)",
        }],
      },
    });
    expect(await screen.findByText("Rate confirmation")).toBeTruthy();
    expect(screen.getByText("the USD 2-5 band is ACE-inferred")).toBeTruthy();
    expect(screen.getByText("responding LLO + Spark")).toBeTruthy();
  });

  it("leads the decisions surface with the conflicting rows, expanded", async () => {
    renderWith({
      ...BASE,
      decisions: {
        total: 2,
        counts: { stated: 1, inferred: 0, conflicting: 1, overridden: 0 },
        rows: [
          {
            ...DECISION,
            id: "quiet-one",
            question: "A settled call",
            evidence_basis: "stated",
          },
          {
            ...DECISION,
            id: "loud-one",
            question: "A contested call",
            evidence_basis: "conflicting",
            conflict_signals: ["source A says X", "source B says Y"],
          },
        ],
      },
    });
    expect(await screen.findByText("A contested call")).toBeTruthy();
    // Flagged rows open by default, so their conflicting signals are
    // already on the page — that is the point of the section.
    expect(screen.getByText("source A says X")).toBeTruthy();
    // The settled one is behind the disclosure.
    expect(screen.queryByText("A settled call")).toBeNull();
    expect(screen.getByText(/Show all 2/)).toBeTruthy();
  });
});
