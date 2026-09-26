/**
 * The Phases screen in replay mode, end to end: the products strip, the
 * spotlight on the beat that built something, the flow panel, and decisions
 * landing only once their skill has finished.
 */
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DemoEvent, DemoTimeline, ReplayProduct } from "@/api/replay";
import type { Decision, OppSnapshot, RunProduct, Step } from "@/api/types.ws";
import { beatAtIndex, EMPTY_REVEAL, revealAt } from "@/components/replay/cursor";
import type { Replay } from "@/components/replay/useReplay";

import { PhaseView } from "../PhaseView";

function step(skill: string, phase: string, ordinal: number): Step {
  return {
    skill_name: skill, display_name: skill, phase, phase_display: phase, ordinal,
    status: "complete", started_at: null, completed_at: null, error: null, has_judge: false,
    is_recurring: false, preview_text: "", judge: null, qa_result: null,
    artifacts: [{
      name: `${skill}.md`, drive_file_id: `f-${skill}`, drive_web_link: "https://drive/x",
      mime_type: "application/vnd.google-apps.document", size_bytes: 10,
      path: `${phase}/${skill}.md`,
    }],
  };
}

const PDD: RunProduct = {
  id: "idea-to-design:pdd", phase: "idea-to-design", key: "pdd", kind: "document",
  title: "Turmeric Market Survey", subtitle: null, url: "https://drive/pdd", file_id: "f-pdd",
  facts: [], producer: "idea-to-pdd", chatbot: null,
};
const APP: RunProduct = {
  id: "commcare-setup:apps.learn", phase: "commcare-setup", key: "apps.learn",
  kind: "commcare_app", title: "Turmeric — FLW Training", subtitle: null,
  url: "https://www.commcarehq.org/a/x/apps/view/1/", file_id: null, facts: [],
  producer: "pdd-to-learn-app", chatbot: null,
};

const decision = (id: string, skill: string, phase: string): Decision =>
  ({
    id, phase, phase_raw: phase, skill, question: `Question ${id}?`, ai_default: "yes",
    override: "", options_considered: [], source: "", status: "ai-default", notes: "",
    override_reasoning: "", evidence_basis: "stated", conflict_signals: [],
  }) as unknown as Decision;

const SNAPSHOT = {
  opp: { slug: "opp", display_name: "Opp" },
  pdd_body: "",
  runs: [{ run_id: "r1", last_actor_at: null }],
  selected_run_id: "r1",
  phases: [
    { name: "idea-to-design", display_name: "Idea to design", ordinal: 1, agent: "a" },
    { name: "commcare-setup", display_name: "CommCare setup", ordinal: 3, agent: "b" },
  ],
  current_run: {
    run_id: "r1", mode: "auto", status: "complete", started_at: null, completed_at: null,
    current_phase: null, current_step: null, skill_versions: {}, notes: "",
    steps: [step("idea-to-pdd", "idea-to-design", 1), step("pdd-to-learn-app", "commcare-setup", 2)],
    decisions: [
      decision("d1", "idea-to-pdd", "idea-to-design"),
      decision("d2", "pdd-to-learn-app", "commcare-setup"),
    ],
    products: [PDD, APP],
  },
} as unknown as OppSnapshot;

const e = (p: Partial<DemoEvent> & Pick<DemoEvent, "seq" | "kind" | "phase">) =>
  ({ t: null, phase_display: p.phase, ...p }) as DemoEvent;

const TIMELINE: DemoTimeline = {
  timing_source: "ordinal", origin: null, wall_seconds: null, ladder: [
    { phase: "idea-to-design", phase_display: "Idea to design", ordinal: 1, steps: [] },
    { phase: "commcare-setup", phase_display: "CommCare setup", ordinal: 3, steps: [] },
  ],
  events: [
    e({ seq: 0, kind: "phase_start", phase: "idea-to-design" }),
    e({ seq: 1, kind: "step_start", phase: "idea-to-design", skill: "idea-to-pdd" }),
    e({ seq: 2, kind: "step_end", phase: "idea-to-design", skill: "idea-to-pdd", status: "complete" }),
    e({ seq: 3, kind: "phase_start", phase: "commcare-setup" }),
    e({ seq: 4, kind: "step_start", phase: "commcare-setup", skill: "pdd-to-learn-app" }),
    e({ seq: 5, kind: "step_end", phase: "commcare-setup", skill: "pdd-to-learn-app", status: "complete" }),
  ],
  products: [
    { ...PDD, reveal_seq: 2 } as ReplayProduct,
    { ...APP, reveal_seq: 5 } as ReplayProduct,
  ],
  flow: {
    "idea-to-pdd": {
      inputs: [{ path: "inputs/", description: "Evidence pack.", producer: "external", producer_phase: "design" }],
      outputs: [{
        path: "idea-to-design/idea-to-pdd.md", description: "The PDD.",
        consumers: [{ skill: "pdd-to-learn-app", phase: "commcare-setup" }],
      }],
    },
    "pdd-to-learn-app": { inputs: [], outputs: [] },
  },
};

function replayAt(index: number, over: Partial<Replay> = {}): Replay {
  const noop = () => {};
  return {
    active: true, loading: false, error: null, timeline: TIMELINE,
    beat: beatAtIndex(TIMELINE, index), reveal: index < 0 ? EMPTY_REVEAL : revealAt(TIMELINE, index),
    total: TIMELINE.events.length, playing: false, highlightsOnly: false, spotlights: true,
    start: noop, stop: noop, toggle: noop, next: noop, prev: noop, restart: noop, goTo: noop,
    goToSkill: noop, toggleHighlights: noop, toggleSpotlights: noop, hold: noop,
    ...over,
  };
}

const renderAt = (replay: Replay) =>
  render(
    <MemoryRouter>
      <PhaseView snapshot={SNAPSHOT} oppSlug="opp" workspaceSlug="ws1" replay={replay} />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve(new Response("# The PDD", { headers: { "Content-Type": "text/markdown" } })),
  ));
});
afterEach(() => vi.unstubAllGlobals());

describe("PhaseView in replay", () => {
  it("pops up what the beat just built, and marks it built in the strip", async () => {
    renderAt(replayAt(2));
    const spotlight = screen.getByRole("dialog", { name: /Just built: Turmeric Market Survey/ });
    expect(within(spotlight).getByText("Just built")).toBeInTheDocument();
    expect(await within(spotlight).findByText("The PDD")).toBeInTheDocument();
    const strip = screen.getByRole("region", { name: "What this run built" });
    expect(within(strip).getByText("Built so far · 1/2")).toBeInTheDocument();
    // The app isn't built yet: its name stays hidden behind its kind.
    expect(within(strip).queryByRole("button", { name: /FLW Training/ })).not.toBeInTheDocument();
  });

  it("shows no spotlight on a beat that built nothing, or with pop-ups off", () => {
    const { unmount } = renderAt(replayAt(1));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    unmount();
    renderAt(replayAt(2, { spotlights: false }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("grows a flow chain: the current step open with its inputs and outputs", () => {
    renderAt(replayAt(2, { spotlights: false }));
    const flow = screen.getByRole("complementary", { name: "Flow" });
    expect(within(flow).getByText("Inputs")).toBeInTheDocument();
    expect(within(flow).getByText("Outputs")).toBeInTheDocument();
    expect(within(flow).getByText(/your inputs/)).toBeInTheDocument();
    expect(within(flow).getByText("→ used in Phase 3")).toBeInTheDocument();
    // Not reached yet: the later step has no card.
    expect(within(flow).queryByText("pdd-to-learn-app")).not.toBeInTheDocument();
  });

  it("folds earlier steps to one line once the replay moves on", () => {
    renderAt(replayAt(5, { spotlights: false }));
    const flow = screen.getByRole("complementary", { name: "Flow" });
    const earlier = within(flow).getByRole("button", { name: /idea-to-pdd/ });
    expect(earlier).toHaveAttribute("aria-expanded", "false");
    expect(within(earlier).getByText("1 in · 1 out")).toBeInTheDocument();
    expect(within(flow).getByRole("button", { name: /pdd-to-learn-app/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("pops up the markdown a step wrote alongside what it built", () => {
    renderAt(replayAt(2));
    const spotlight = screen.getByRole("dialog", { name: /Just built/ });
    // PDD product first, then the step's own idea-to-pdd.md as a second tab.
    expect(within(spotlight).getByText("1 of 2", { exact: false })).toBeInTheDocument();
    expect(within(spotlight).getByRole("button", { name: "Idea to PDD" })).toBeInTheDocument();
  });

  it("lands a decision only once its skill has finished", () => {
    const { container } = renderAt(replayAt(2, { spotlights: false }));
    // Phase tiles count overridden decisions only; check the data path via the
    // phase panel instead — idea-to-design is open (the cursor's phase).
    expect(within(container).getByText("Question d1?")).toBeInTheDocument();
    expect(within(container).queryByText("Question d2?")).not.toBeInTheDocument();
  });
});

it("outside a replay, lists everything the run built", () => {
  renderAt(replayAt(-1, { active: false, timeline: null }));
  expect(screen.getByText("What this run built")).toBeInTheDocument();
  // Glossary terms render as their own <abbr>, so match the chip's full text.
  expect(screen.getByRole("button", { name: /Turmeric — FLW Training/ })).toBeInTheDocument();
  expect(screen.queryByRole("complementary", { name: "Flow" })).not.toBeInTheDocument();
});
