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
  build: null,
  // Null on a run that never took the deep gate — which is most of them.
  deep_qa: null,
  connect: null,
  training: null,
  assistant: null,
  walkthroughs: [],
  dashboards: [],
  synthetic: null,
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

/**
 * A walkthrough from a run that recorded no DDD loop state. Every field
 * null / false — absence must never be dressed up as reassurance, so
 * this is what "we don't know whether the loop converged" looks like,
 * not "it converged".
 */
const DDD_NONE = {
  terminal_status: null,
  iterations_completed: null,
  measures_pre_fix_artifact: false,
  note: null,
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
        ddd: DDD_NONE,
      }],
    });
    expect(
      await screen.findByText(/did not pass quality review/),
    ).toBeTruthy();
    expect(screen.queryByText("Open deck")).toBeNull();
  });

  // ─── The walkthrough score and its qualifiers (ace-web#740) ────────

  it("scores a walkthrough out of 5, the rubric's actual scale", async () => {
    // The canopy DDD concept rubric is anchored 1–5
    // (skills/ddd-concept-eval/rubric.yaml, anchors "5"…"1"). The page
    // rendered `/10`, so the audited run's concept 2.0 — 2 of 5 —
    // showed as 2 of 10: roughly half as good as it actually was.
    renderWith({
      ...BASE,
      walkthroughs: [{
        persona: "Community progression",
        url: "https://labs/ddd/x",
        eval_score: 2,
        availability: "available",
        withheld_reason: null,
        access: "admin",
        ddd: DDD_NONE,
      }],
    });
    expect(await screen.findByText(/eval 2\/5/)).toBeTruthy();
    expect(screen.queryByText(/eval 2\/10/)).toBeNull();
  });

  it("never shows a bare score for a loop that stopped without converging", async () => {
    // THE regression test for the audited run: the page showed
    // "eval 2/10" and a video link while the run state recorded
    // stopped_not_converged, 0 end-to-end iterations, and that the
    // render measures a PRE-FIX artifact.
    renderWith({
      ...BASE,
      walkthroughs: [{
        persona: "Community progression",
        url: "https://labs/ddd/x",
        eval_score: 2,
        availability: "available",
        withheld_reason: null,
        access: "admin",
        ddd: {
          terminal_status: "stopped_not_converged",
          iterations_completed: 0,
          measures_pre_fix_artifact: true,
          note: "READ THIS BEFORE QUOTING THE 2.0.",
        },
      }],
    });
    expect(
      await screen.findByText(/stopped before it converged/),
    ).toBeTruthy();
    // The pre-fix caveat is the one that makes the LINKED VIDEO
    // misleading, not just the number.
    expect(
      screen.getByText(/measure a version that has since been fixed/),
    ).toBeTruthy();
  });

  // No pass/fail collapse. `converged_clean` and
  // `converged_with_open_questions` are precisely the pair a boolean
  // would fuse, and precisely the pair a reader needs to tell apart —
  // so they get one test each, asserting the OTHER one's wording is
  // absent.
  const walkthroughWithStatus = (terminal_status: string) => ({
    persona: "Community progression",
    url: "https://labs/ddd/x",
    eval_score: 4,
    availability: "available" as const,
    withheld_reason: null,
    access: "admin" as const,
    ddd: { ...DDD_NONE, terminal_status },
  });

  it("renders converged_clean as its own outcome", async () => {
    renderWith({
      ...BASE,
      walkthroughs: [walkthroughWithStatus("converged_clean")],
    });
    expect(await screen.findByText(/finished clean/)).toBeTruthy();
    expect(screen.queryByText(/with open questions/)).toBeNull();
  });

  it("renders converged_with_open_questions as a different outcome", async () => {
    renderWith({
      ...BASE,
      walkthroughs: [walkthroughWithStatus("converged_with_open_questions")],
    });
    expect(await screen.findByText(/with open questions/)).toBeTruthy();
    expect(screen.queryByText(/finished clean/)).toBeNull();
  });

  it("surfaces an unrecognised terminal status verbatim rather than dropping it", async () => {
    renderWith({
      ...BASE,
      walkthroughs: [walkthroughWithStatus("stalled_on_a_gate")],
    });
    expect(
      await screen.findByText(/review loop status: stalled_on_a_gate/),
    ).toBeTruthy();
  });

  it("says nothing about the loop when the run recorded nothing", async () => {
    // Absence is not reassurance. A run predating these fields must
    // render exactly as it did, with no invented "converged".
    renderWith({
      ...BASE,
      walkthroughs: [{
        persona: "Community progression",
        url: "https://labs/ddd/x",
        eval_score: 4,
        availability: "available",
        withheld_reason: null,
        access: "admin",
        ddd: DDD_NONE,
      }],
    });
    expect(await screen.findByText(/eval 4\/5/)).toBeTruthy();
    expect(screen.queryByText(/review loop/)).toBeNull();
    expect(screen.queryByText(/since been fixed/)).toBeNull();
  });

  // ─── What the assistant claims to know (ace-web#740) ───────────────

  it("makes no training claim when the run recorded no knowledge sources", async () => {
    // The page carried a constant: "Trained on the design doc, training
    // pack, and app guides for this opportunity." On the audited run the
    // opp collection held 16 files and none of the five training-pack
    // documents this same page links were among them.
    renderWith({
      ...BASE,
      assistant: {
        ocs_url: "https://ocs/console",
        access: "admin",
        public_id: "pid",
        embed_key: "ek",
        knowledge_sources: [],
      },
    });
    expect(
      await screen.findByText("Ask questions about this opportunity."),
    ).toBeTruthy();
    expect(screen.queryByText(/training pack/)).toBeNull();
  });

  it("states what the assistant knows when — and only when — the run says so", async () => {
    renderWith({
      ...BASE,
      assistant: {
        ocs_url: "https://ocs/console",
        access: "admin",
        public_id: "pid",
        embed_key: "ek",
        knowledge_sources: ["the design doc", "the app guides"],
      },
    });
    expect(
      await screen.findByText(/It was given the design doc and the app guides\./),
    ).toBeTruthy();
  });

  // ─── One number per population (ace-web#740) ───────────────────────

  it("does not present the open-question count as a subset of the decisions", async () => {
    // The Overview read "51 calls ACE made building this run, 23 it
    // couldn't settle" — splicing decisions.total and
    // open_questions.items.length, two different populations. Nothing in
    // that run equalled 23 of 51.
    renderWith({
      ...BASE,
      decisions: {
        total: 51,
        counts: { stated: 30, inferred: 17, conflicting: 4, overridden: 0 },
        rows: [],
      },
      open_questions: {
        url: null,
        access: "unknown",
        items: [
          { title: "Rate", detail: "d", owner: null, answered_in: null, blocking: null },
          { title: "Device", detail: "d", owner: null, answered_in: null, blocking: null },
        ],
      },
    });
    expect(
      await screen.findByText(/51 calls ACE made building this run\./),
    ).toBeTruthy();
    expect(
      screen.getByText(/Separately, 2 open questions the run couldn't settle/),
    ).toBeTruthy();
    expect(
      screen.queryByText(/51 calls ACE made building this run, 2 it couldn't settle/),
    ).toBeNull();
  });

  // ─── An unmeasurable link is not called public (ace-web#740) ───────

  it("tags a Drive link whose sharing state could not be read", async () => {
    renderWith({
      ...BASE,
      design: {
        docs: [
          { title: "Program Design Document", url: "https://docs/pdd", access: "unknown" },
        ],
      },
    });
    expect(await screen.findByText("Program Design Document")).toBeTruthy();
    expect(screen.getAllByText("access unverified").length).toBe(1);
    // Not the wrong tag in the other direction either.
    expect(screen.queryByText("admin only")).toBeNull();
  });

  it("tags the open-questions source doc too, which renders outside SummaryRow", async () => {
    // That link is hand-rolled on the Decisions tab, so it does not
    // inherit the row's tag logic. Leaving it untagged would read as
    // "anyone can open this" — the ace-web#740 bug in a second place.
    renderWith({
      ...BASE,
      open_questions: {
        url: "https://docs/open-questions",
        access: "unknown",
        items: [{ title: "Rate", detail: "d", owner: null, answered_in: null, blocking: null }],
      },
    });
    await openDecisionsTab();
    expect(await screen.findByText("Source document")).toBeTruthy();
    expect(screen.getAllByText("access unverified").length).toBe(1);
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
          blocking: null,
        }],
      },
    });
    await openDecisionsTab();
    expect(await screen.findByText("Rate confirmation")).toBeTruthy();
    expect(screen.getByText("the USD 2-5 band is ACE-inferred")).toBeTruthy();
    expect(screen.getByText("responding LLO + Spark")).toBeTruthy();
  });

  const TWO_PHASES: OppSummaryPayload = {
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
          phase_raw: "4-connect-setup",
          phase_label: "Connect setup",
          phase_ordinal: 4,
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
  };

  it("organises the decisions by phase, the way the Workbench does", async () => {
    // Phase is the structure of the tab, not something you reach by
    // expanding a disclosure — a reader has to be able to see WHERE in
    // the flow a call came from (Jonathan, 2026-08-14).
    renderWith(TWO_PHASES);
    await openDecisionsTab();
    expect(await screen.findByText("Design")).toBeTruthy();
    expect(screen.getByText("Connect setup")).toBeTruthy();
    expect(screen.getByText("Phase 4")).toBeTruthy();
  });

  it("opens the contested rows in their phase, and leaves the routine ones collapsed", async () => {
    renderWith(TWO_PHASES);
    await openDecisionsTab();
    // The conflicting row is expanded IN its phase section, so its
    // competing signals are on screen at first paint.
    expect(screen.getAllByText("A contested call").length).toBeGreaterThan(0);
    expect(await screen.findByText("source A says X")).toBeTruthy();
    // The phase with nothing contested stays collapsed, so 40 routine
    // rows can't bury the 2 that need an eye.
    expect(screen.queryByText("A settled call")).toBeNull();
    fireEvent.click(screen.getByText("Connect setup"));
    expect(screen.getByText("A settled call")).toBeTruthy();
  });

  it("jumps to a flagged row rather than rendering it twice", async () => {
    renderWith(TWO_PHASES);
    await openDecisionsTab();
    // One entry in the "worth your eye" list + the row itself in its
    // phase — the list is a jump list, and clicking it lands on the row.
    const hits = screen.getAllByText("A contested call");
    expect(hits.length).toBe(2);
    fireEvent.click(hits[0]);
    expect(screen.getByText("source A says X")).toBeTruthy();
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
    await screen.findByText("Design");
    expect(screen.getAllByText("A contested call").length).toBeGreaterThan(0);
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

  it("never asks a signed-in viewer to type their name, or to confirm", async () => {
    // Logged in ⇒ never anonymous: the session identity is used, so we
    // already know who is editing and there is nothing left to confirm.
    // A member gets the Workbench's click-and-done editing.
    const post = vi.spyOn(api, "postDecisionEdit").mockResolvedValue(EDIT);
    renderWith({ ...CONFLICTED, viewer: { is_member: true } });
    await openDecisionsTab();
    fireEvent.click(await screen.findByRole("button", { name: /the other one/i }));
    expect(screen.queryByLabelText("Your name")).toBeNull();
    expect(screen.queryByText("Save this answer")).toBeNull();
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][4]).toMatchObject({ value: "the other one" });
  });

  it("asks for a name once, then edits click-and-done like the Workbench", async () => {
    // The confirm step exists for exactly one situation: we don't yet
    // know who is editing. Once they've told us, a Save button on every
    // one of 42 rows is the barrier this surface exists to remove.
    const post = vi.spyOn(api, "postDecisionEdit").mockResolvedValue(EDIT);
    renderWith(CONFLICTED);
    await openDecisionsTab();

    fireEvent.click(await screen.findByRole("button", { name: /the other one/i }));
    fireEvent.change(screen.getByLabelText("Your name"), {
      target: { value: "Anne Kuhlmann" },
    });
    // The mode does not flip mid-draft — the Save button they are aiming
    // at stays where it is.
    expect(screen.getByText("Save this answer")).toBeTruthy();
    fireEvent.click(screen.getByText("Save this answer"));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));

    // Second change: no name field, no Save button, no confirm step.
    expect(await screen.findByText(/saved as/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^the pick/i }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Save this answer")).toBeNull();
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

  // ── The three MISLEADING defects an anonymous audit found on
  //    spark-facilitator/20260828-0703 (dimagi-internal/ace#1867,
  //    ace-web#743, ace-web#744). Each renders a caveat the page had no
  //    vocabulary for, and each stays silent when the run is clean.

  it("says a partial build is partial, and names the gate that failed", async () => {
    renderWith({
      ...BASE,
      apps: [
        { kind: "Learn", name: "Learn app", hq_url: "https://hq/l", access: "admin" },
        { kind: "Deliver", name: "Deliver app", hq_url: "https://hq/d", access: "admin" },
      ],
      build: {
        status: "partial",
        verdict: "partial-deliver-eval-blocked-on-phase1-gap",
        note: "Both apps are released and Phase 4 is unblocked.",
        failing_checks: [{
          name: "pdd-to-deliver-app-eval",
          verdict: "fail",
          detail: "entity_state_fidelity - PDD declares no taxonomy row.",
        }],
        carried_blockers: [],
      },
    });
    expect(await screen.findByText(/did not all pass/)).toBeTruthy();
    expect(screen.getByText(/pdd-to-deliver-app-eval/)).toBeTruthy();
    expect(screen.getByText(/entity_state_fidelity/)).toBeTruthy();
    expect(screen.getByText(/Phase 4 is unblocked/)).toBeTruthy();
  });

  it("adds nothing to a clean build", async () => {
    renderWith({
      ...BASE,
      apps: [{ kind: "Learn", name: "Learn app", hq_url: "https://hq/l", access: "admin" }],
      build: null,
    });
    expect(await screen.findByText("Learn app")).toBeTruthy();
    expect(screen.queryByText(/did not all pass/)).toBeNull();
    expect(screen.queryByText(/build status/)).toBeNull();
  });

  it("labels the dashboards as generated data, with the run's own counts", async () => {
    renderWith({
      ...BASE,
      dashboards: [{ title: "Verification", url: "https://labs/one", access: "admin" }],
      synthetic: {
        is_synthetic: true,
        provider: "ace-run",
        labs_opp_id: 10054,
        visits: 223,
        completed_works: 0,
        cohort_size: 12,
        cohort_population: "the facilitator cohort",
      },
    });
    expect(
      await screen.findByText(/Demonstration data . not real programme activity/),
    ).toBeTruthy();
    expect(screen.getByText(/223 generated records/)).toBeTruthy();
    expect(screen.getByText(/12 synthetic the facilitator cohort/)).toBeTruthy();
    expect(screen.getByText(/No payments were made against it/)).toBeTruthy();
  });

  it("does not label a run that generated nothing", async () => {
    renderWith({
      ...BASE,
      dashboards: [{ title: "Verification", url: "https://labs/one", access: "admin" }],
      synthetic: null,
    });
    expect(await screen.findByText("Verification")).toBeTruthy();
    expect(screen.queryByText(/Demonstration data/)).toBeNull();
  });

  it("shows an open question's title, and when it has to be answered by", async () => {
    renderWith({
      ...BASE,
      open_questions: {
        url: "https://drive/oq",
        access: "admin",
        items: [{
          title: "What does Spark pay CBFs today?",
          detail: "The single largest unknown on this opportunity.",
          owner: "Spark",
          answered_in: "solicitation responses",
          blocking: "Before Phase 8",
        }],
      },
    });
    await openDecisionsTab();
    expect(await screen.findByText("What does Spark pay CBFs today?")).toBeTruthy();
    expect(screen.getByText("Needed by")).toBeTruthy();
    expect(screen.getByText("Before Phase 8")).toBeTruthy();
  });
});


// ═══════════════════════════════════════════════════════════════════
// Deep QA (`/ace:qa-deep`).
//
// The section exists so a reader is told what the LAUNCH STEP is told:
// Phase 9 `llo-launch` refuses activation on a missing or stale deep
// verdict. Its one hard rule is that a score must never render as a
// verdict — spark-facilitator/20260828-0703 scores 8.03 against a 7.0
// bar and its gate is `iterate` anyway.
// ═══════════════════════════════════════════════════════════════════

/** Stage A of spark-facilitator/20260828-0703, with its real numbers. */
const OCS_STAGE = {
  stage: "assistant" as const,
  label: "Support assistant",
  ran: true,
  ran_at: "2026-09-01T15:05:00Z",
  gate: "iterate",
  verdict: "warn",
  score: 8.03,
  threshold: 7.0,
  counts: { total: 68, pass: 58, warn: 8, fail: 2 },
  dimensions: [{ name: "correctness", score: 7.23, weight: 0.3 }],
  findings: [
    {
      severity: "BLOCKER",
      message: "opp-50 improvised a cash-handover pathway the design does not contain.",
    },
  ],
  items: [
    {
      ref: "opp-50",
      verdict: "fail",
      score: 3.0,
      note: "Invented a cash-handover pathway.",
    },
  ],
  freshness: [
    {
      basis: "published chatbot version",
      verdict_value: "3",
      current_value: "3",
      is_current: true,
    },
  ],
  is_stale: false,
};

const APPS_NOT_RUN = {
  stage: "apps" as const,
  label: "CommCare apps",
  ran: false,
  ran_at: null,
  gate: null,
  verdict: null,
  score: null,
  threshold: null,
  counts: { total: 0, pass: 0, warn: 0, fail: 0 },
  dimensions: [],
  findings: [],
  items: [],
  freshness: [],
  is_stale: null,
};

describe("deep QA", () => {
  it("is completely absent when the gate never ran", async () => {
    renderWith(BASE);
    await screen.findByText("Program Design Document");
    expect(screen.queryByText("Deep QA")).toBeNull();
    // Not an empty shell either — no stray heading, no "not run" row.
    expect(screen.queryByText(/deep-tested/i)).toBeNull();
  });

  it("leads with the gate, and says the score does not settle it", async () => {
    renderWith({
      ...BASE,
      deep_qa: { stages: [OCS_STAGE, APPS_NOT_RUN] },
    });
    await screen.findByText("Deep QA");
    expect(
      screen.getByText(/has not cleared the deep gate/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/58 passed/)).toBeInTheDocument();
    expect(screen.getByText(/2 failed/)).toBeInTheDocument();
    // The reconciliation sentence — without it, 8.03 is the only thing a
    // reader takes away from a run that is not ready to launch.
    expect(
      screen.getByText(/a deep pass\s+needs zero failures/i),
    ).toBeInTheDocument();
    // The failing item is NAMED, not just counted.
    expect(screen.getByText("opp-50")).toBeInTheDocument();
  });

  it("says plainly when only one stage was run", async () => {
    renderWith({
      ...BASE,
      deep_qa: { stages: [OCS_STAGE, APPS_NOT_RUN] },
    });
    await screen.findByText("Deep QA");
    expect(screen.getByText(/Not deep-tested on this run/i)).toBeInTheDocument();
    expect(
      screen.getByText(/absence of a finding is not a clean result/i),
    ).toBeInTheDocument();
  });

  it("warns when the verdict describes something other than what is deployed", async () => {
    const stale = {
      ...OCS_STAGE,
      is_stale: true,
      freshness: [
        {
          basis: "published chatbot version",
          verdict_value: "3",
          current_value: "5",
          is_current: false,
        },
      ],
    };
    renderWith({
      ...BASE,
      deep_qa: { stages: [stale, APPS_NOT_RUN] },
    });
    await screen.findByText("Deep QA");
    expect(
      screen.getByText(/does not describe what is running today/i),
    ).toBeInTheDocument();
  });

  it("claims nothing about freshness when the server could not compare", async () => {
    // The honest degrade: no comparison, so the page shows the date and
    // leaves the judgement to the reader rather than asserting `fresh`.
    renderWith({
      ...BASE,
      deep_qa: {
        stages: [{ ...OCS_STAGE, freshness: [], is_stale: null }, APPS_NOT_RUN],
      },
    });
    await screen.findByText("Deep QA");
    expect(screen.getByText(/^Run on /)).toBeInTheDocument();
    expect(screen.queryByText(/still what is deployed/i)).toBeNull();
    expect(screen.queryByText(/does not describe what is running today/i)).toBeNull();
  });
});
