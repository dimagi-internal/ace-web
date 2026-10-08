import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as lineageApi from "@/api/lineage";
import * as api from "@/api/oppSummary";
import type { OppSummaryPayload } from "@/api/oppSummary";
import OppSummaryPage from "@/pages/OppSummaryPage";
import {
  MEMBER_LINEAGE,
  OUTSIDER_LINEAGE,
} from "@/components/opps/decisions/lineage/__tests__/sparkLineage.fixture";

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
  // Null on every run that authored no claims — most of them — and the
  // section must then not render at all.
  claims: null,
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
  open_asks: null,
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
async function openDecisionsTab({ expand = true } = {}) {
  fireEvent.click(await screen.findByText("Review the decisions"));
  await screen.findByText("About these decisions");
  // "Everything else ACE decided" starts collapsed; most tests read rows in
  // it, so open it the way a reader would.
  const expandAll = screen.queryByText("Expand all");
  if (expand && expandAll) fireEvent.click(expandAll);
}

/** Rows start collapsed; open one by its question, the way a reader would. */
async function openRow(question: string) {
  fireEvent.click(await screen.findByText(question));
}

describe("OppSummaryPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("links the design docs a reviewer is meant to comment on", async () => {
    renderWith(BASE);
    expect(await screen.findByText("Program Design Document")).toBeTruthy();
  });

  // ─── "What changed because you asked" (ace#2420) ──────────────────

  it("draws nothing for claims on a run that authored none", async () => {
    // Most opportunities have none. A "no claims" heading on every other
    // run teaches reviewers to skip the section.
    renderWith(BASE);
    await screen.findByText("Program Design Document");
    expect(screen.queryByText("What changed because you asked")).toBeNull();
  });

  it("puts the claim set ABOVE the design docs — it is a returning reviewer's first question", async () => {
    renderWith({
      ...BASE,
      claims: {
        summary: "1/2 met, 1 not met",
        total: 2,
        all_met: false,
        counts: { met: 1, unmet: 1, not_reached: 0, indeterminate: 0, unanswered: 0 },
        error: null,
        people: [{
          person: "Sophie Feintuch",
          claims: [
            {
              id: "a",
              claim: "The Deliver app carries no payment marker on consumption support.",
              verdict: "MET",
              evidence_kind: "probed",
              authored_by: "ace",
              person: "Sophie Feintuch",
              quote: null,
              artifact: "deliver-app",
              checkable_at: "commcare-setup",
              says: "Nobody is paid for consumption support.",
              evidence: null,
              would_settle_it: null,
            },
            {
              id: "b",
              claim: "My nine comments land in this run's design.",
              verdict: "UNMET",
              evidence_kind: "judged",
              authored_by: "counterpart",
              person: "Sophie Feintuch",
              quote: "whether my comments land",
              artifact: "composed-pdd",
              checkable_at: "idea-to-design",
              says: "Two of your nine comments were not accounted for.",
              evidence: null,
              would_settle_it: null,
            },
          ],
        }],
      },
    });
    const claims = await screen.findByText("What changed because you asked");
    const design = screen.getByText("Design");
    expect(
      claims.compareDocumentPosition(design) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // The unmet one accuses rather than going missing, and the bar she
    // set herself is marked as hers.
    expect(screen.getByText("Not met")).toBeTruthy();
    expect(screen.getByText(/you asked for this one/i)).toBeTruthy();
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
    // Matched on the opening sentence rather than the whole string: the blurb
    // now also tells the reader WHERE to ask (the in-page widget, ace#1839).
    // The claim this test guards is the absent one — no training pack asserted
    // when the run recorded no knowledge sources.
    expect(
      await screen.findByText(/^Ask questions about this opportunity\./),
    ).toBeTruthy();
    expect(screen.queryByText(/training pack/)).toBeNull();
    expect(screen.queryByText(/It was given/)).toBeNull();
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

  it("counts one population: the asks are a subset of the decisions", async () => {
    // The Overview once read "51 calls ACE made building this run, 23 it
    // couldn't settle", splicing the decisions count with a separate
    // ledger's. There is no ledger now (2026-10-07): nothing but the
    // decisions log is counted.
    renderWith({
      ...BASE,
      decisions: {
        total: 51,
        counts: { stated: 30, inferred: 17, conflicting: 4, overridden: 0 },
        rows: [],
      },
    });
    expect(
      await screen.findByText(/51 calls ACE made building this run\./),
    ).toBeTruthy();
    expect(screen.queryByText(/Separately,/)).toBeNull();
    expect(screen.queryByText(/couldn't settle/)).toBeNull();
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

  it("distinguishes 'not started yet' from 'Not created'", async () => {
    renderWith({
      ...BASE,
      stage: {
        label: "solicitation",
        pending_sections: ["selected_llo", "launch"],
        skipped: [],
        caveats: [],
      },
    });
    const notStarted = await screen.findAllByText(
      "Not started — this run is at the solicitation stage",
    );
    // LLO + Live rows.
    expect(notStarted.length).toBe(2);
    // Sections whose phase HAS run keep the plain missing state.
    expect(screen.getAllByText("Not created").length).toBeGreaterThan(0);
  });

  it("gives a skipped phase's sections the run's reason, never 'Not created'", async () => {
    // spark-facilitator/20261001-2208: halted by design after Phase 8, so
    // Execution and Outcomes are not part of the run at all.
    const reason = "Not part of this run — it stopped after the solicitation stage, by design";
    renderWith({
      ...BASE,
      stage: {
        label: "solicitation",
        pending_sections: [],
        skipped: [
          { phase: "execution-management", sections: ["selected_llo", "launch"], reason },
          {
            phase: "closeout",
            sections: ["cycle_grade", "opp_eval", "learnings"],
            reason,
          },
        ],
        caveats: [],
      },
    });
    // LLO, Live, Score, Learnings.
    expect((await screen.findAllByText(reason)).length).toBe(4);
    expect(screen.queryByText(/Not started/)).toBeNull();
  });

  it("qualifies a section whose phase finished without a clean verdict", async () => {
    renderWith({
      ...BASE,
      training: {
        deck: null,
        docs: [{ title: "FAQ", url: "https://docs/faq", access: "public" }],
      },
      dashboards: [{ title: "Programme", url: "https://labs/d/1", access: "public" }],
      stage: {
        label: "solicitation",
        pending_sections: [],
        skipped: [],
        caveats: [
          {
            phase: "qa-and-training",
            sections: ["training"],
            verdict: "proceed-with-warn",
            text: "Finished with warnings that were accepted so the run could continue.",
          },
          {
            phase: "synthetic-data-and-workflows",
            sections: ["walkthroughs", "dashboards"],
            verdict: "passed-with-deferred-evals",
            text: "Built; some quality checks were deferred.",
          },
        ],
      },
    });
    expect(
      await screen.findByText(
        "Finished with warnings that were accepted so the run could continue.",
      ),
    ).toBeTruthy();
    // Dashboards carry it; walkthroughs has no entries, so no caveat there.
    expect(screen.getAllByText("Built; some quality checks were deferred.").length).toBe(1);
  });

  // ── Orientation (run-surface audit, 2026-10-03) ─────────────────

  it("tells an outside reader who drafted this, what we need and how to respond", async () => {
    renderWith({
      ...BASE,
      decisions: {
        total: 1,
        counts: { stated: 1, inferred: 0, conflicting: 0, overridden: 0 },
        rows: [{ ...DECISION, review_ask: "recommended-confirmation" }],
      },
    });
    const about = await screen.findByRole("region", { name: "About this page" });
    const text = about.textContent ?? "";
    expect(text).toContain("ACE, Dimagi’s AI program engine");
    expect(text).toContain("Dimagi staff review it");
    expect(text).toContain("confirm the 1 decision marked “Confirm before launch”");
    expect(text).toContain("reply to the email that sent you this link");
    expect(text).toContain("Dimagi’s team reads every reply");
    expect(text).toContain("LLO");
    expect(text).toContain("FLW");
    expect(text).not.toContain("CommCare Connect");
    // The orientation's own link goes to the Decisions tab.
    fireEvent.click(screen.getByText("Go to the decisions"));
    expect(await screen.findByText("A question")).toBeTruthy();
  });

  it("draws no orientation for a workspace member", async () => {
    renderWith({ ...BASE, viewer: { is_member: true } });
    await screen.findByText("Program Design Document");
    expect(screen.queryByRole("region", { name: "About this page" })).toBeNull();
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
    renderWith({ ...TWO_PHASES, viewer: { is_member: true } });
    await openDecisionsTab();
    expect(await screen.findByText("Design")).toBeTruthy();
    expect(screen.getByText("Connect setup")).toBeTruthy();
    expect(screen.getByText("Phase 4")).toBeTruthy();
  });

  it("labels an outsider's phase groups with plain stage names, no ordinal", async () => {
    // "PHASE 3 · CommCare Setup" means nothing outside ACE.
    const rows = TWO_PHASES.decisions!.rows;
    renderWith({
      ...TWO_PHASES,
      decisions: {
        ...TWO_PHASES.decisions!,
        rows: [
          { ...rows[0], phase_label: "CommCare Setup", stage_label: "App build" },
          rows[1],
        ],
      },
    });
    await openDecisionsTab();
    expect(await screen.findByText("App build")).toBeTruthy();
    expect(screen.queryByText("CommCare Setup")).toBeNull();
    expect(screen.queryByText(/^Phase \d+$/)).toBeNull();
  });

  it("shows every row's question and answer in full without expanding it", async () => {
    // Jonathan, 2026-10-03: the row used to be an ellipsized one-liner, so
    // learning anything meant expanding every row. Phases now start open
    // and a collapsed row carries the full question and the answer in force.
    renderWith(TWO_PHASES);
    await openDecisionsTab();
    expect(await screen.findByText("A settled call")).toBeTruthy();
    expect(screen.getByText("A contested call")).toBeTruthy();
    expect(screen.getAllByText("the pick").length).toBe(2);
    // …but the detail is still one click away, not on screen at first paint.
    expect(screen.queryByText("source A says X")).toBeNull();
    // A phase still collapses.
    fireEvent.click(screen.getByText("Connect setup"));
    expect(screen.queryByText("A settled call")).toBeNull();
  });

  it("notes conflicting sources quietly, with no call to action or count", async () => {
    renderWith(TWO_PHASES);
    await openDecisionsTab();
    expect(await screen.findByText("ACE's sources disagreed")).toBeTruthy();
    expect(screen.queryByText(/need your eye/i)).toBeNull();
    expect(screen.queryByText(/worth your eye/i)).toBeNull();
    expect(screen.queryByText(/resolved a conflict/i)).toBeNull();
    // The always-present ai-default chip is gone.
    expect(screen.queryByText("ai-default")).toBeNull();
    await openRow("A contested call");
    expect(screen.getByText("source A says X")).toBeTruthy();
  });

  it("keeps the full question and answer visible when a row is expanded", async () => {
    // The bug: expanding `pilot-scope-window` left its header truncated
    // with an ellipsis, so the full question/answer never appeared. Nothing
    // in the header may clip any more.
    const q = "Which slice of the FCAP arc does the pilot cover, given the facilitator cadence?";
    const a = "Goal Setting subphase, FCAP steps 1-7, ending before the Proposal Generator";
    renderWith({
      ...BASE,
      decisions: {
        total: 1,
        counts: { stated: 0, inferred: 1, conflicting: 0, overridden: 0 },
        rows: [{
          ...DECISION, id: "pilot-scope-window", question: q, ai_default: a,
          options_considered: [a, "Full FCAP arc"], evidence_basis: "inferred",
        }],
      },
    });
    await openDecisionsTab();
    await openRow(q);
    const header = screen.getByText(q).closest("button")!;
    expect(header.getAttribute("aria-expanded")).toBe("true");
    expect(header.textContent).toContain(a);
    for (const el of header.querySelectorAll("*")) {
      expect(el.getAttribute("class") ?? "").not.toMatch(/\btruncate\b/);
    }
  });

  it("shows ACE's plain-language summary under the answer when it wrote one", async () => {
    renderWith({
      ...BASE,
      decisions: {
        total: 1,
        counts: { stated: 1, inferred: 0, conflicting: 0, overridden: 0 },
        rows: [{ ...DECISION, plain: "Workers cover the first seven steps only." }],
      },
    });
    await openDecisionsTab();
    expect(await screen.findByText("Workers cover the first seven steps only.")).toBeTruthy();
  });

  // ── Confirm before launch (ACE `review_ask`, 2026-10) ────────────
  // The SAME row as every other decision, pinned on top — not a card.

  const ASKS: OppSummaryPayload = {
    ...BASE,
    decisions: {
      total: 3,
      counts: { stated: 3, inferred: 0, conflicting: 0, overridden: 0 },
      rows: [
        {
          ...DECISION,
          id: "window",
          question: "Which slice does the pilot cover?",
          ai_default: "Goal Setting",
          options_considered: ["Goal Setting", "Full arc"],
          review_ask: "recommended-confirmation",
          confirm_reason: "Only Spark knows the facilitator cadence.",
          check_at: "Learn module 1",
        },
        { ...DECISION, id: "routine", question: "A routine call" },
        {
          ...DECISION,
          id: "internal-rule",
          question: "An internal rule",
          audience: "internal",
        },
        {
          ...DECISION,
          id: "old-one",
          question: "An earlier version",
          superseded_by: "routine",
        },
      ],
    },
  };
  const MEMBER = { viewer: { is_member: true } };

  it("starts the reference phases collapsed, below the asks", async () => {
    renderWith(ASKS);
    await openDecisionsTab({ expand: false });
    expect(await screen.findByText("Everything else ACE decided")).toBeTruthy();
    expect(screen.getByText(/Nothing here needs you/)).toBeTruthy();
    // The pinned ask is on the page; reference rows wait for "Expand all".
    expect(screen.getByText("Which slice does the pilot cover?")).toBeTruthy();
    expect(screen.getByText("Expand all")).toBeTruthy();
    // The tally and lineage live in a collapsed "About these decisions".
    expect(screen.getByText("About these decisions").closest("details")!.open).toBe(false);
  });

  it("keeps an expanded row to the choice and ACE's reasoning", async () => {
    renderWith(ASKS);
    await openDecisionsTab();
    await openRow("Which slice does the pilot cover?");
    // Provenance folds behind one disclosure; ACE's skill and row id are gone.
    expect(screen.getByText("Sources and evidence").closest("details")!.open).toBe(false);
    expect(screen.queryByText("Raised by")).toBeNull();
  });

  it("pins the confirm-before-launch rows on top, as ordinary rows", async () => {
    renderWith(ASKS);
    await openDecisionsTab();
    // The first match is the pinned section's own header.
    const pinned = (await screen.findAllByText("Confirm before launch"))[0];
    const choices = screen.getByText("Everything else ACE decided");
    expect(
      pinned.compareDocumentPosition(choices) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // Same row component: its header is the shared toggle button, carrying
    // the marker and the reason in the row itself.
    const row = screen.getByText("Which slice does the pilot cover?").closest("button")!;
    expect(row.getAttribute("aria-expanded")).toBe("false");
    // The group is titled "Confirm before launch"; the row does not repeat it.
    expect(row.textContent).not.toContain("Confirm before launch");
    expect(row.textContent).toContain("Only Spark knows the facilitator cadence.");
    expect(row.textContent).toContain("Learn module 1");
    // One decision, one home.
    expect(screen.getAllByText("Which slice does the pilot cover?").length).toBe(1);
  });

  it("hides internal and replaced rows until asked", async () => {
    renderWith(ASKS);
    await openDecisionsTab();
    expect(await screen.findByText("A routine call")).toBeTruthy();
    expect(screen.queryByText("An internal rule")).toBeNull();
    expect(screen.queryByText("An earlier version")).toBeNull();

    fireEvent.click(screen.getByText(/Show 1 internal/));
    expect(screen.getByText("An internal rule")).toBeTruthy();
    expect(screen.getByText("internal")).toBeTruthy();

    fireEvent.click(screen.getByText(/Show 1 replaced/));
    expect(screen.getByText("An earlier version")).toBeTruthy();
    expect(screen.getByText(/replaced — no longer in force/)).toBeTruthy();
  });

  it("lets a member Confirm any row, recorded distinctly from a change", async () => {
    const post = vi.spyOn(api, "postDecisionEdit").mockResolvedValue({
      decision_id: "window",
      override: "Goal Setting",
      reasoning: "",
      decided_by_name: "Enock",
      decided_by_verified: true,
      decided_at: "2026-10-03T10:00:00+00:00",
      source_run_id: "20260813-2126",
      is_revert: false,
      confirmed: true,
      history: [],
    });
    renderWith({ ...ASKS, ...MEMBER });
    await openDecisionsTab();
    await openRow("Which slice does the pilot cover?");
    fireEvent.click(screen.getByRole("button", { name: /^Confirm: Goal Setting/ }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][3]).toBe("window");
    expect(post.mock.calls[0][4]).toEqual({ value: "Goal Setting", confirm: true });
    expect(await screen.findByText(/All 1 answered/)).toBeTruthy();
    expect(screen.getAllByText(/confirmed by Enock/i).length).toBeGreaterThan(0);

    // …and the same Confirm is on a routine row too.
    await openRow("A routine call");
    expect(screen.getByRole("button", { name: /^Confirm: the pick/ })).toBeTruthy();
  });

  it("counts the confirmations still to make in the Overview headline", async () => {
    renderWith(ASKS);
    expect(
      await screen.findByText(/1 recommended to confirm before launch\./),
    ).toBeTruthy();
    expect(screen.queryByText(/need your eye/)).toBeNull();
  });

  it("counts a confirmed or changed row as answered, and a revert as not", async () => {
    const edit = (over: Partial<api.PublicDecisionEdit>): api.PublicDecisionEdit => ({
      override: "Goal Setting",
      reasoning: "",
      decided_by_name: "Enock",
      decided_by_verified: true,
      decided_at: "2026-10-03T10:00:00+00:00",
      source_run_id: "20260813-2126",
      is_revert: false,
      history: [],
      ...over,
    });
    const { unmount } = renderWith({
      ...ASKS, decision_edits: { window: edit({ confirmed: true }) },
    });
    expect(
      await screen.findByText(/All 1 recommended confirmations are answered\./),
    ).toBeTruthy();
    unmount();
    renderWith({ ...ASKS, decision_edits: { window: edit({ is_revert: true }) } });
    expect(
      await screen.findByText(/1 recommended to confirm before launch\./),
    ).toBeTruthy();
  });

  // ── Plain-language display fields (ACE decisions-contract) ──────────

  it("prefers plain_question / plain_value, keeping the exact wording in the detail", async () => {
    renderWith({
      ...BASE,
      decisions: {
        total: 1,
        counts: { stated: 1, inferred: 0, conflicting: 0, overridden: 0 },
        rows: [{
          ...DECISION,
          question: "Which FLW amount within the PDD's proposed band is configured?",
          ai_default: "7500",
          options_considered: ["7500", "10000"],
          plain_question: "What should a facilitator be paid per verified meeting?",
          plain_value: "7,500 MWK",
          plain: "The middle of the proposed band.",
        }],
      },
    });
    await openDecisionsTab();
    const q = await screen.findByText("What should a facilitator be paid per verified meeting?");
    const header = q.closest("button")!;
    expect(header.textContent).toContain("7,500 MWK");
    expect(header.textContent).toContain("The middle of the proposed band.");
    expect(header.textContent).not.toContain("Which FLW amount");
    fireEvent.click(q);
    expect(screen.getByText("ACE's internal wording")).toBeTruthy();
    expect(screen.getByText("Which FLW amount within the PDD's proposed band is configured?")).toBeTruthy();
    expect(screen.getByText("Exact option")).toBeTruthy();
  });

  it("never lets a plain value mask a human change", async () => {
    renderWith({
      ...BASE,
      decisions: {
        total: 1,
        counts: { stated: 1, inferred: 0, conflicting: 0, overridden: 1 },
        rows: [{
          ...DECISION, ai_default: "7500", override: "9000", status: "overridden",
          plain_value: "7,500 MWK", options_considered: ["7500", "9000"],
        }],
      },
    });
    await openDecisionsTab();
    const header = (await screen.findByText("A question")).closest("button")!;
    expect(header.textContent).toContain("9000");
    expect(header.textContent).not.toContain("7,500 MWK");
  });

  it("leads with ACE's plain sentence and keeps the raw option behind the row", async () => {
    // A row with `plain` but no `plain_value`: the sentence already states
    // the answer, so the raw option (jargon to an outsider) moves to the
    // expanded detail as "Exact option".
    renderWith({
      ...BASE,
      decisions: {
        total: 1,
        counts: { stated: 1, inferred: 0, conflicting: 0, overridden: 0 },
        rows: [{
          ...DECISION,
          question: "How is the 3-per-step payment cap enforced?",
          ai_default: "payable_slot in key plus Phase 4 rule",
          options_considered: ["payable_slot in key plus Phase 4 rule", "clamped key only"],
          plain: "Only the 1st to 3rd meeting on a step is paid.",
        }],
      },
    });
    await openDecisionsTab();
    const q = await screen.findByText("Only the 1st to 3rd meeting on a step is paid.");
    const header = q.closest("button")!;
    expect(header.textContent).not.toContain("payable_slot");
    fireEvent.click(q);
    expect(screen.getByText("Exact option")).toBeTruthy();
  });

  // ── Members write; everyone reads ───────────────────────────────

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

  it("says 'React to any of them' when nothing is asked of the reviewer", async () => {
    renderWith(CONFLICTED);
    expect(await screen.findByText(/React to any of them\./)).toBeTruthy();
  });

  it("keeps the review surface one URL away, not one link away", async () => {
    renderWith(CONFLICTED);
    expect(await screen.findByText("Overview")).toBeTruthy();
    expect(screen.getByText("Decisions")).toBeTruthy();
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

  it("is read-only for anyone not signed in as a member — no name fields, no write controls", async () => {
    // Jonathan, 2026-10-03: "no anonymous editing at all".
    const edit = vi.spyOn(api, "postDecisionEdit");
    const react = vi.spyOn(api, "postDecisionReaction");
    renderWith({ ...ASKS, ...CONFLICTED, decisions: ASKS.decisions });
    await openDecisionsTab();
    expect(await screen.findByText(/Sign in to confirm, change or comment/)).toBeTruthy();
    await openRow("Which slice does the pilot cover?");
    expect(screen.queryByLabelText("Your name")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Confirm:/ })).toBeNull();
    // Options are shown, but as static pills, not buttons.
    expect(screen.queryByRole("button", { name: /Full arc/ })).toBeNull();
    expect(screen.getByText("Full arc")).toBeTruthy();
    // "Sign in" replaces both the editor and the comment box.
    expect(screen.getByText("Sign in to edit")).toBeTruthy();
    expect(screen.getByText("Sign in to comment")).toBeTruthy();
    expect(screen.queryByText(/Ask a question or raise a concern/)).toBeNull();
    const href = screen.getByText("Sign in to edit").closest("a")!.getAttribute("href")!;
    expect(href).toMatch(/\/auth\/login\/\?next=/);
    expect(edit).not.toHaveBeenCalled();
    expect(react).not.toHaveBeenCalled();
  });

  const EDIT = {
    decision_id: "loud-one",
    override: "the other one",
    reasoning: "",
    decided_by_name: "Anne Kuhlmann",
    decided_by_verified: true,
    decided_at: "2026-08-14T10:00:00+00:00",
    source_run_id: "20260813-2126",
    is_revert: false,
    history: [],
  };

  it("lets a member change an answer click-and-done, with no name and no Save", async () => {
    const post = vi.spyOn(api, "postDecisionEdit").mockResolvedValue(EDIT);
    renderWith({ ...CONFLICTED, ...MEMBER });
    await openDecisionsTab();
    await openRow("A contested call");
    fireEvent.click(await screen.findByRole("button", { name: /the other one/i }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0].slice(0, 4)).toEqual([
      "dimagi-team", "spark-facilitator", "20260813-2126", "loud-one",
    ]);
    // The body carries no identity — the server takes the session's.
    expect(post.mock.calls[0][4]).toEqual({ value: "the other one", reasoning: undefined });
    expect(screen.queryByLabelText("Your name")).toBeNull();
    expect(screen.queryByText("Save this answer")).toBeNull();
    expect(await screen.findByText(/changed by Anne Kuhlmann/)).toBeTruthy();
  });

  it("lets a member comment on one row, as themselves", async () => {
    const post = vi.spyOn(api, "postDecisionReaction").mockResolvedValue({
      decision_id: "loud-one",
      reviewer: "Anne Kuhlmann",
      comment: "The later date is right.",
      received_at: "2026-08-14",
      feedback_ref: "20260814-public-anne-kuhlmann/loud-one",
    });
    renderWith({ ...CONFLICTED, ...MEMBER });
    await openDecisionsTab();
    await openRow("A contested call");
    fireEvent.click(await screen.findByText(/Not ready to decide\? Ask what you.d need to know/));
    // Before anything is sent, the row says a comment is not an edit.
    expect(screen.getAllByText(/A comment doesn.t change the answer/).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText("Your comment on this decision"), {
      target: { value: "The later date is right." },
    });
    expect(screen.queryByLabelText("Your name")).toBeNull();
    fireEvent.click(screen.getByText("Post comment"));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][4]).toEqual({ comment: "The later date is right." });
    expect(await screen.findByText(/The answer above is unchanged/)).toBeTruthy();
    expect(await screen.findByText("The later date is right.")).toBeTruthy();
  });

  it("shows who changed a row, and lets a member put the old answer back", async () => {
    const post = vi.spyOn(api, "postDecisionEdit").mockResolvedValue(EDIT);
    renderWith({
      ...CONFLICTED,
      ...MEMBER,
      decision_edits: {
        "loud-one": {
          override: "the other one",
          reasoning: "the source we trust says so",
          decided_by_name: "Anne Kuhlmann",
          decided_by_verified: true,
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
    await openRow("A contested call");
    expect(await screen.findByText(/changed by Anne Kuhlmann/)).toBeTruthy();
    fireEvent.click(screen.getByText(/1 earlier/));
    fireEvent.click(screen.getByText("Restore"));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][4]).toMatchObject({ value: "the pick" });
  });

  it("surfaces the server's refusal of a change", async () => {
    vi.spyOn(api, "postDecisionEdit").mockRejectedValue(
      new api.ReactionError("Only members of this workspace can change, confirm or comment on its decisions."),
    );
    renderWith({ ...CONFLICTED, ...MEMBER });
    await openDecisionsTab();
    await openRow("A contested call");
    fireEvent.click(await screen.findByRole("button", { name: /the other one/i }));
    expect(await screen.findByText(/Only members of this workspace/)).toBeTruthy();
  });

  it("renders reactions the run already collected, to anyone", async () => {
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
    await openRow("A contested call");
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

  // ─── The outsider pass (spark-facilitator/20261001-2208) ───────────

  it("says a run that stopped by design is paused, and drops the run id for outsiders", async () => {
    renderWith({
      ...BASE,
      opp: { ...BASE.opp, status: "in_progress", end_date: null },
      stage: {
        label: "solicitation",
        pending_sections: [],
        skipped: [],
        caveats: [],
        paused: "Paused — waiting for an implementing organisation",
      },
    });
    expect(
      await screen.findByText("Paused — waiting for an implementing organisation"),
    ).toBeTruthy();
    expect(screen.queryByText("In progress")).toBeNull();
    expect(screen.queryByText("run 20260813-2126")).toBeNull();
  });

  it("still shows a member the run id in the top bar", async () => {
    renderWith({ ...BASE, viewer: { is_member: true } });
    expect(await screen.findByText("run 20260813-2126")).toBeTruthy();
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

/**
 * The open-questions ledger folds into decision rows (ACE spec 2026-10-04).
 * Rows follow spark/spark-facilitator/20261001-2208: the real
 * `working-language` confirmation, the spec's one gated question
 * (`rct-sample-overlap`, required before award, answered through the
 * solicitation) and a deferred expansion row.
 */
describe("review asks", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  const row = (over: Record<string, unknown>) =>
    ({ ...DECISION, ...over }) as api.ReviewDecision;
  const ROWS = [
    row({
      id: "working-language",
      question: "Working language(s) and who reviews translations?",
      plain_question: "Have the Chichewa and Tumbuka translations been checked?",
      review_ask: "recommended-confirmation",
      confirm_reason: "The text was produced by AI.",
      owner: "partner",
      answer_channel: "review",
    }),
    row({
      id: "rct-sample-overlap",
      phase_raw: "8-solicitation-management",
      phase_label: "Solicitation",
      phase_ordinal: 8,
      question: "Trial overlap?",
      plain_question: "Can pilot communities overlap with Spark's trial communities?",
      ai_default: "OPEN",
      options_considered: ["OPEN"],
      review_ask: "required-before",
      needed_by: "award",
      confirm_reason: "The award could pick trial communities.",
      owner: "partner",
      answer_channel: "solicitation:q-rct-overlap",
    }),
    row({
      id: "rwanda-two-cbf-attribution",
      question: "How is payment attributed where two CBFs share one community?",
      status: "deferred",
      revisit_when: "Spark plans an expansion beyond Malawi.",
      owner: "Spark",
    }),
    row({ id: "routine", question: "A routine call" }),
  ];
  const DECISIONS = {
    total: 4,
    counts: {
      stated: 4, inferred: 0, conflicting: 0, overridden: 0,
      to_confirm: 1, to_answer: 1, deferred: 1,
    },
    rows: ROWS,
  } as NonNullable<OppSummaryPayload["decisions"]>;
  it("groups the gated question under 'Answer before …' with who answers and where", async () => {
    renderWith({ ...BASE, decisions: DECISIONS });
    await openDecisionsTab();
    expect(
      await screen.findByText("Answer before an implementing organisation is chosen"),
    ).toBeTruthy();
    expect(screen.getByText("Confirm before launch", { selector: "span.text-sm" })).toBeTruthy();
    // The group names the stage; the row does not repeat it as a chip.
    expect(screen.queryByText("Answer before award")).toBeNull();
    // The solicitation channel, in plain words — and no question id for an outsider.
    expect(
      screen.getByText(/Through the call for implementing organisations/),
    ).toBeTruthy();
    expect(screen.queryByText(/q-rct-overlap/)).toBeNull();
    expect(screen.getAllByText(/The programme partner/).length).toBe(2);
  });

  it("shows a member the solicitation question id", async () => {
    renderWith({ ...BASE, viewer: { is_member: true }, decisions: DECISIONS });
    await openDecisionsTab();
    expect(await screen.findByText(/question q-rct-overlap/)).toBeTruthy();
  });

  it("parks a deferred row, collapsed, with when to revisit it", async () => {
    renderWith({ ...BASE, decisions: DECISIONS });
    await openDecisionsTab();
    const heading = await screen.findByText("Not needed for this pilot");
    expect(screen.getByText("1 to revisit later")).toBeTruthy();
    // Collapsed: the row is not on the page until the section is opened.
    expect(screen.queryByText(/Spark plans an expansion/)).toBeNull();
    fireEvent.click(heading);
    expect(await screen.findByText(/Spark plans an expansion beyond Malawi/)).toBeTruthy();
    // One decision, one home: it is not also under "Everything else ACE decided".
    expect(
      screen.getAllByText("How is payment attributed where two CBFs share one community?"),
    ).toHaveLength(1);
  });

  it("counts both kinds of ask in the orientation block", async () => {
    renderWith({ ...BASE, decisions: DECISIONS });
    expect(
      await screen.findByText(
        /Please answer the 1 question marked “Answer before …”, and confirm the 1 decision/,
      ),
    ).toBeTruthy();
    expect(screen.getByText(/1 question to answer, and 1 recommended to confirm/)).toBeTruthy();
  });

  it("counts a row a person already ruled on as answered", async () => {
    const ruled = {
      ...DECISIONS,
      rows: ROWS.map((d) =>
        d.id === "working-language" ? { ...d, status: "human-decided" as const } : d,
      ),
    };
    renderWith({ ...BASE, decisions: ruled });
    expect(await screen.findByText(/1 question to answer\./)).toBeTruthy();
    expect(screen.queryByText(/recommended to confirm before launch/)).toBeNull();
  });

  it("asks only through decision rows — no separate open-questions list", async () => {
    renderWith({ ...BASE, decisions: DECISIONS });
    expect(await screen.findByText("Questions for you")).toBeTruthy();
    expect(screen.getByText(/they are on the Decisions tab/)).toBeTruthy();
    expect(screen.queryByText(/Separately,/)).toBeNull();
    await openDecisionsTab();
    expect(screen.queryByText("Open questions")).toBeNull();
  });
});

/**
 * Decision lineage on the Decisions tab — the real spark clone's payload
 * (`sparkLineage.fixture.ts`), joined to rows by id.
 */
describe("decision lineage on the Decisions tab", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  const row = (over: Record<string, unknown>) =>
    ({ ...DECISION, ...over }) as api.ReviewDecision;
  const DECISIONS = {
    total: 3,
    counts: { stated: 3, inferred: 0, conflicting: 0, overridden: 0 },
    rows: [
      row({ id: "working-language", question: "Which working languages?" }),
      row({ id: "program-reuse-vs-create-spark", question: "Reuse the program or create one?" }),
      row({
        id: "open-question-recording-path-whole-community-group-declines",
        question: "What if a whole group declines?",
      }),
    ],
  } as NonNullable<OppSummaryPayload["decisions"]>;

  it("shows an outsider the strip and plain badges, and filters every group", async () => {
    vi.spyOn(lineageApi, "getDecisionLineage").mockResolvedValue(OUTSIDER_LINEAGE);
    renderWith({ ...BASE, decisions: DECISIONS });
    await openDecisionsTab();
    expect(await screen.findByText("This version")).toBeTruthy();
    expect(await screen.findByText("changed in this version")).toBeTruthy();
    // "Carried over unchanged" is the norm on a copied run, so it is not drawn.
    expect(screen.queryByText("carried over unchanged from the 25 Sep 2026 version")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Changed 1" }));
    expect(screen.queryByText("Which working languages?")).toBeNull();
    expect(screen.getByText("Reuse the program or create one?")).toBeTruthy();
  });

  it("gives a member run ids and the history", async () => {
    vi.spyOn(lineageApi, "getDecisionLineage").mockResolvedValue(MEMBER_LINEAGE);
    renderWith({ ...BASE, viewer: { is_member: true }, decisions: DECISIONS });
    await openDecisionsTab();
    // Carried over verbatim in every run: no "evolved" history to tell, and
    // no "carried … unchanged" badge on the summary either.
    await openRow("Which working languages?");
    expect(screen.queryByText("carried from dimagi-team / 20260925-1536 unchanged")).toBeNull();
    expect(screen.queryByText("How this decision evolved")).toBeNull();
    // Create → Reuse → Create: that one did evolve.
    await openRow("Reuse the program or create one?");
    expect(screen.getByText("How this decision evolved")).toBeTruthy();
  });

  it("lets a member widen each history to every run of the opportunity", async () => {
    const spy = vi
      .spyOn(lineageApi, "getDecisionLineage")
      .mockImplementation(async (_w, _s, _r, scope) => ({ ...MEMBER_LINEAGE, scope: scope ?? "lineage" }));
    renderWith({ ...BASE, viewer: { is_member: true }, decisions: DECISIONS });
    await openDecisionsTab();
    fireEvent.click(await screen.findByText("History: the runs this one was built from"));
    expect(await screen.findByText("History: every run of this opportunity")).toBeTruthy();
    expect(spy).toHaveBeenLastCalledWith("dimagi-team", "spark-facilitator", "20260813-2126", "opp");
  });

  it("renders the tab as before when lineage cannot be read", async () => {
    vi.spyOn(lineageApi, "getDecisionLineage").mockRejectedValue(new Error("500"));
    renderWith({ ...BASE, decisions: DECISIONS });
    await openDecisionsTab();
    expect(await screen.findByText("Which working languages?")).toBeTruthy();
    expect(screen.queryByRole("group", { name: /Filter decisions/ })).toBeNull();
  });
});

/**
 * The Decisions tab leads with what needs the reader. "120 decisions" read
 * to an outside reviewer as 120 questions when 25 were asks, 6 were
 * deferred and the rest were calls ACE already made (spark/20261004-1706).
 */
describe("decisions headline leads with the asks", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  const row = (over: Record<string, unknown>) =>
    ({ ...DECISION, ...over }) as api.ReviewDecision;
  const ROWS = [
    row({ id: "c1", question: "Confirm one?", review_ask: "recommended-confirmation" }),
    row({ id: "c2", question: "Confirm two?", review_ask: "recommended-confirmation" }),
    row({ id: "d1", question: "Later maybe?", status: "deferred", revisit_when: "scale-up" }),
    row({ id: "a1", question: "ACE call one?" }),
    row({ id: "a2", question: "ACE call two?" }),
    row({ id: "a3", question: "ACE call three?" }),
    // History never counts: not an ask, not a call.
    row({
      id: "old",
      question: "Replaced?",
      review_ask: "recommended-confirmation",
      superseded_by: "c1",
    }),
  ];
  const PAYLOAD: OppSummaryPayload = {
    ...BASE,
    decisions: {
      total: 6,
      counts: { stated: 6, inferred: 0, conflicting: 0, overridden: 0 },
      rows: ROWS,
    } as NonNullable<OppSummaryPayload["decisions"]>,
  };

  it("headlines asks, then deferred, then ACE's own calls — the total is secondary", async () => {
    renderWith(PAYLOAD);
    await openDecisionsTab();
    const headline = await screen.findByTestId("decisions-headline");
    expect(headline.textContent).toBe("2 to confirm · 1 deferred · 3 decided by ACE (for review)");
    expect(screen.getByText(/6 load-bearing calls in all/)).toBeTruthy();
  });

  it("puts the ask count on the tab, not the size of the log", async () => {
    renderWith(PAYLOAD);
    expect(await screen.findByText("2 to confirm")).toBeTruthy();
    expect(screen.queryByText("6")).toBeNull();
  });

  it("drops the tab badge once every ask is answered", async () => {
    renderWith({
      ...PAYLOAD,
      decisions: {
        ...PAYLOAD.decisions!,
        rows: ROWS.map((d) =>
          d.id === "c1" || d.id === "c2" ? { ...d, status: "human-decided" } : d,
        ),
      },
    });
    await openDecisionsTab();
    const headline = await screen.findByTestId("decisions-headline");
    expect(headline.textContent).toMatch(/^2 to confirm, all answered · /);
    expect(screen.queryByText(/^\d+ to confirm$/)).toBeNull();
  });
});
