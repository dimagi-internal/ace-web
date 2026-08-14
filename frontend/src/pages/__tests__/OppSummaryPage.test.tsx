import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api/oppSummary";
import type { OppSummaryPayload } from "@/api/oppSummary";
import { rememberIdentity } from "@/components/opps/decisions/reviewerIdentity";
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
  reactions: { total: 0, by_decision: {} },
  decision_edits: {},
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

/** The review surface is a tab now — open it the way a reader would. */
async function openDecisionsTab() {
  fireEvent.click(await screen.findByText("Review the decisions"));
}

describe("OppSummaryPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // The reviewer's name is remembered in localStorage so working
    // through several rows costs one typing — which means it leaks
    // between tests in this file unless cleared. Written through the
    // same helper the app uses: the test env's storage stub has no
    // `.clear()`.
    rememberIdentity({ name: "", email: "" });
  });

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
    await openDecisionsTab();
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
    await openDecisionsTab();
    expect(await screen.findByText("A contested call")).toBeTruthy();
    // Flagged rows open by default, so their conflicting signals are
    // already on the page — that is the point of the section.
    expect(screen.getByText("source A says X")).toBeTruthy();
    // The settled one is behind the disclosure.
    expect(screen.queryByText("A settled call")).toBeNull();
    expect(screen.getByText(/Show all 2/)).toBeTruthy();
  });

  // ── The response affordance ─────────────────────────────────────
  // #708 shipped 42 decisions with no way to say anything about any of
  // them, which is the skim-and-agree failure the log exists to fix,
  // just in a nicer shape.

  const CONFLICTED: OppSummaryPayload = {
    ...BASE,
    decisions: {
      total: 1,
      counts: { stated: 0, inferred: 0, conflicting: 1, overridden: 0 },
      rows: [{
        ...DECISION,
        id: "loud-one",
        question: "A contested call",
        evidence_basis: "conflicting",
        conflict_signals: ["source A says X"],
      }],
    },
  };

  it("keeps the review surface one URL away, not one link away", async () => {
    // A partner gets ONE link. The decisions live on a tab of the same
    // page, so pointing someone at them is still that link + ?tab=.
    renderWith(CONFLICTED);
    expect(await screen.findByText("Overview")).toBeTruthy();
    expect(screen.getByText("Decisions")).toBeTruthy();
    // Overview first — the decisions body is not on screen yet.
    expect(screen.queryByText("A contested call")).toBeNull();
    await openDecisionsTab();
    expect(await screen.findByText("A contested call")).toBeTruthy();
  });

  it("draws no tab strip when a run has nothing to review", async () => {
    renderWith(BASE);
    expect(await screen.findByText("Program Design Document")).toBeTruthy();
    expect(screen.queryByText("Decisions")).toBeNull();
    expect(screen.queryByText("Review the decisions")).toBeNull();
  });

  it("lets a partner react to ONE decision row, and requires a name", async () => {
    const post = vi.spyOn(api, "postDecisionReaction").mockResolvedValue({
      decision_id: "loud-one",
      reviewer: "Anne Kuhlmann",
      comment: "The later date is right.",
      received_at: "2026-08-14",
      feedback_ref: "20260814-public-anne-kuhlmann/loud-one",
    });
    renderWith(CONFLICTED);
    await openDecisionsTab();

    // Conflicting rows open expanded, so the reply box is one click away.
    fireEvent.click(await screen.findByText(/Say what you.d want to know/));
    fireEvent.change(screen.getByLabelText("Your comment on this decision"), {
      target: { value: "The later date is right." },
    });
    // Name is required — an unattributable comment can't be answered or
    // credited, which is the whole value of the ledger it lands in.
    expect((screen.getByText("Send") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Your name"), {
      target: { value: "Anne Kuhlmann" },
    });
    fireEvent.click(screen.getByText("Send"));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0].slice(0, 4)).toEqual([
      "dimagi-team", "spark-facilitator", "20260813-2126", "loud-one",
    ]);
    // …and it shows up immediately, rather than after the 60s read cache.
    expect(await screen.findByText("The later date is right.")).toBeTruthy();
  });

  // ── Editing ──────────────────────────────────────────────────────
  //
  // Anyone with the link can change an answer in place. No account, no
  // proposal state, no promotion step, and a member's edit is the same
  // act as a partner's (Jonathan, 2026-08-14). What makes that safe is
  // attribution + history + undo, so those are tested as behaviour, not
  // as decoration.

  const EDIT = {
    decision_id: "loud-one",
    override: "the other one",
    reasoning: "",
    decided_by_name: "Anne Kuhlmann",
    decided_by_verified: false,
    decided_at: "2026-08-14T10:00:00+00:00",
    source_run_id: "20260813-2126",
    is_revert: false,
    history: [],
  };

  it("lets an anonymous visitor change a decision's answer in place", async () => {
    const post = vi.spyOn(api, "postDecisionEdit").mockResolvedValue(EDIT);
    renderWith(CONFLICTED);
    await openDecisionsTab();

    // Pick a different option. Nothing has left the browser yet — the
    // name is asked at submit, never as a gate before someone can click.
    fireEvent.click(await screen.findByRole("button", { name: /the other one/i }));
    expect(post).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Your name"), {
      target: { value: "Anne Kuhlmann" },
    });
    fireEvent.click(screen.getByText("Save this answer"));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0].slice(0, 4)).toEqual([
      "dimagi-team", "spark-facilitator", "20260813-2126", "loud-one",
    ]);
    expect(post.mock.calls[0][4]).toMatchObject({
      value: "the other one", reviewer: "Anne Kuhlmann",
    });
    // …and the row re-renders as changed immediately, rather than after
    // the 60s read cache.
    expect(await screen.findByText(/changed by Anne Kuhlmann/)).toBeTruthy();
  });

  it("will not submit an anonymous change without a name", async () => {
    const post = vi.spyOn(api, "postDecisionEdit").mockResolvedValue(EDIT);
    renderWith(CONFLICTED);
    await openDecisionsTab();
    fireEvent.click(await screen.findByRole("button", { name: /the other one/i }));
    expect((screen.getByText("Save this answer") as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(post).not.toHaveBeenCalled();
  });

  it("never asks a signed-in viewer to type their name", async () => {
    // Logged in ⇒ never anonymous. The session identity is used instead.
    renderWith({ ...CONFLICTED, viewer: { is_member: true } });
    await openDecisionsTab();
    fireEvent.click(await screen.findByRole("button", { name: /the other one/i }));
    expect(screen.queryByLabelText("Your name")).toBeNull();
    expect((screen.getByText("Save this answer") as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it("shows who changed a row, and lets anyone put the old answer back", async () => {
    // The safety mechanism, in full: reviewer 2 sees reviewer 1's name,
    // sees what it used to say, and can restore it in one click.
    const post = vi.spyOn(api, "postDecisionEdit").mockResolvedValue(EDIT);
    renderWith({
      ...CONFLICTED,
      decision_edits: {
        "loud-one": {
          override: "the other one",
          reasoning: "the source we trust says so",
          decided_by_name: "Anne Kuhlmann",
          decided_by_verified: false,
          decided_at: "2026-08-14T10:00:00+00:00",
          source_run_id: "20260813-2126",
          is_revert: false,
          history: [{
            override: "the pick",
            reasoning: "",
            decided_by_name: "Ben Okoro",
            decided_by_verified: true,
            decided_at: "2026-08-13T09:00:00+00:00",
          }],
        },
      },
    });
    await openDecisionsTab();

    expect(await screen.findByText(/changed by Anne Kuhlmann/)).toBeTruthy();
    // The self-reported marker is shown, never enforced.
    expect(screen.getAllByText("(self-reported)").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByText(/1 earlier/));
    fireEvent.click(screen.getByText("Restore"));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][4]).toMatchObject({ value: "the pick" });
  });

  it("surfaces the server's refusal of a change", async () => {
    vi.spyOn(api, "postDecisionEdit").mockRejectedValue(
      new api.ReactionError("Give it a few minutes before sending another change."),
    );
    renderWith(CONFLICTED);
    await openDecisionsTab();
    fireEvent.click(await screen.findByRole("button", { name: /the other one/i }));
    fireEvent.change(screen.getByLabelText("Your name"), {
      target: { value: "Anne Kuhlmann" },
    });
    fireEvent.click(screen.getByText("Save this answer"));
    expect(
      await screen.findByText(/Give it a few minutes before sending another change/),
    ).toBeTruthy();
  });

  it("surfaces the server's refusal instead of pretending it saved", async () => {
    vi.spyOn(api, "postDecisionReaction").mockRejectedValue(
      new api.ReactionError("Give it a few minutes before sending another comment."),
    );
    renderWith(CONFLICTED);
    await openDecisionsTab();
    fireEvent.click(await screen.findByText(/Say what you.d want to know/));
    fireEvent.change(screen.getByLabelText("Your comment on this decision"), {
      target: { value: "one more thought" },
    });
    fireEvent.change(screen.getByLabelText("Your name"), {
      target: { value: "Anne Kuhlmann" },
    });
    fireEvent.click(screen.getByText("Send"));
    expect(await screen.findByText(/Give it a few minutes/)).toBeTruthy();
  });

  it("renders reactions the run already collected", async () => {
    renderWith({
      ...CONFLICTED,
      reactions: {
        total: 1,
        by_decision: {
          "loud-one": [{
            reviewer: "Anne Kuhlmann",
            comment: "We start in October, not September.",
            received_at: "2026-08-14",
            feedback_ref: "20260814-public-anne-kuhlmann/loud-one",
          }],
        },
      },
    });
    await openDecisionsTab();
    expect(await screen.findByText("We start in October, not September.")).toBeTruthy();
    expect(screen.getByText(/Anne Kuhlmann/)).toBeTruthy();
  });
});
