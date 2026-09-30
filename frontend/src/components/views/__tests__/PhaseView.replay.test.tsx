/**
 * The Phases screen, end to end. In replay: the spotlight on the beat that
 * built (or photographed) something, the flow chain with what each step built,
 * screenshots withheld until the beat that took them, and decisions landing
 * only once their skill has finished. Outside replay: the per-phase rail.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchRunFlow, type DemoEvent, type DemoTimeline, type ReplayProduct } from "@/api/replay";
import type { Decision, OppSnapshot, ProductPreview, RunProduct, Step } from "@/api/types.ws";
import { beatAtIndex, EMPTY_REVEAL, revealAt } from "@/components/replay/cursor";
import { clearViewCache } from "@/components/viewers/viewCache";
import type { Replay } from "@/components/replay/useReplay";

import { PhaseView } from "../PhaseView";

// openapi-fetch binds `fetch` when the client is created, so the rail's flow
// request is mocked at the module rather than through the global stub.
vi.mock("@/api/replay", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/replay")>()),
  fetchRunFlow: vi.fn(),
}));

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
  facts: [], producer: "idea-to-pdd", chatbot: null, featured: true,
};
const APP: RunProduct = {
  id: "commcare-setup:apps.learn", phase: "commcare-setup", key: "apps.learn",
  kind: "commcare_app", title: "Turmeric — FLW Training", subtitle: null,
  url: "https://www.commcarehq.org/a/x/apps/view/1/", file_id: null, facts: [],
  producer: "pdd-to-learn-app", chatbot: null, featured: true,
};
const SHOT: ProductPreview = {
  file_id: "f-shot", name: "01-home.png", caption: "Learn app home",
  mime_type: "image/png", captured_by: "app-screenshot-capture",
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
    { name: "qa-and-training", display_name: "QA and training", ordinal: 6, agent: "c" },
  ],
  current_run: {
    run_id: "r1", mode: "auto", status: "complete", started_at: null, completed_at: null,
    current_phase: null, current_step: null, skill_versions: {}, notes: "",
    steps: [
      step("idea-to-pdd", "idea-to-design", 1),
      step("pdd-to-learn-app", "commcare-setup", 2),
      step("app-screenshot-capture", "qa-and-training", 3),
    ],
    decisions: [
      decision("d1", "idea-to-pdd", "idea-to-design"),
      decision("d2", "pdd-to-learn-app", "commcare-setup"),
    ],
    products: [PDD, { ...APP, previews: [SHOT] }],
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
    e({ seq: 6, kind: "phase_start", phase: "qa-and-training" }),
    e({ seq: 7, kind: "step_start", phase: "qa-and-training", skill: "app-screenshot-capture" }),
    e({ seq: 8, kind: "step_end", phase: "qa-and-training", skill: "app-screenshot-capture", status: "complete" }),
  ],
  products: [
    { ...PDD, reveal_seq: 2 } as ReplayProduct,
    { ...APP, reveal_seq: 5, previews: [{ ...SHOT, reveal_seq: 8 }] } as ReplayProduct,
  ],
  flow: {
    "idea-to-pdd": {
      inputs: [{ path: "inputs/", description: "Evidence pack.", producer: "external", producer_phase: "design" }],
      outputs: [{
        path: "idea-to-design/idea-to-pdd.md", description: "The PDD.",
        consumers: [{ skill: "pdd-to-learn-app", phase: "commcare-setup" }],
      }],
    },
    "pdd-to-learn-app": {
      inputs: [{
        path: "idea-to-design/idea-to-pdd.md", description: "The PDD.",
        producer: "idea-to-pdd", producer_phase: "idea-to-design",
      }],
      outputs: [],
    },
    "app-screenshot-capture": { inputs: [], outputs: [] },
  },
};

function replayAt(index: number, over: Partial<Replay> = {}): Replay {
  const noop = () => {};
  return {
    active: true, loading: false, error: null, timeline: TIMELINE,
    beat: beatAtIndex(TIMELINE, index), reveal: index < 0 ? EMPTY_REVEAL : revealAt(TIMELINE, index),
    total: TIMELINE.events.length, playing: false,
    start: noop, stop: noop, toggle: noop, next: noop, prev: noop, restart: noop, goTo: noop,
    goToSkill: noop, hold: noop,
    ...over,
  };
}

const renderAt = (replay: Replay, path = "/") =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <PhaseView snapshot={SNAPSHOT} oppSlug="opp" workspaceSlug="ws1" replay={replay} />
    </MemoryRouter>,
  );

/** Routes the viewer's fetches: a screenshot as an image, any other file as
 *  markdown. */
function stubFetch() {
  const urlOf = (input: RequestInfo | URL) =>
    typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    if (urlOf(input).includes("f-shot")) {
      return Promise.resolve(new Response(new Blob(["png"]), { headers: { "Content-Type": "image/png" } }));
    }
    return Promise.resolve(new Response("# The PDD", { headers: { "Content-Type": "text/markdown" } }));
  }));
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:shot" }));
}

beforeEach(() => {
  clearViewCache();
  stubFetch();
  vi.mocked(fetchRunFlow).mockResolvedValue(TIMELINE.flow ?? {});
});
afterEach(() => vi.unstubAllGlobals());

describe("PhaseView in replay", () => {
  it("pops up a featured output as it is built", async () => {
    renderAt(replayAt(2));
    const spotlight = screen.getByRole("dialog", { name: /Just built: Turmeric Market Survey/ });
    expect(await within(spotlight).findByText("The PDD")).toBeInTheDocument();
  });

  it("does not pop up an output the summary doesn't feature", () => {
    const timeline = {
      ...TIMELINE,
      products: TIMELINE.products?.map((p) => ({ ...p, featured: false })),
    } as DemoTimeline;
    renderAt(replayAt(2, { timeline, beat: beatAtIndex(timeline, 2) }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("pops the apps up again when Phase 6 photographs them", () => {
    renderAt(replayAt(8));
    expect(
      screen.getByRole("dialog", { name: /Just photographed: Turmeric — FLW Training/ }),
    ).toBeInTheDocument();
  });

  it("shows what the beat just built on the card of the step that built it", () => {
    renderAt(replayAt(2));
    const flow = screen.getByRole("complementary", { name: "Flow" });
    expect(within(flow).getByText("Built so far · 1/2")).toBeInTheDocument();
    expect(within(flow).getByText("Built")).toBeInTheDocument();
    expect(within(flow).getByRole("button", { name: /Turmeric Market Survey/ })).toBeInTheDocument();
    // The app isn't built yet: nothing names it.
    expect(within(flow).queryByRole("button", { name: /FLW Training/ })).not.toBeInTheDocument();
  });

  it("withholds an app's screenshots until the beat that took them", () => {
    renderAt(replayAt(5));
    const flow = screen.getByRole("complementary", { name: "Flow" });
    expect(within(flow).getByRole("button", { name: /FLW Training/ })).toBeInTheDocument();
    // Built in Phase 3, not photographed until Phase 6.
    expect(within(flow).queryByRole("list", { name: /Screenshots of/ })).not.toBeInTheDocument();
  });

  it("shows the app under Photographed when Phase 6 photographs it", async () => {
    renderAt(replayAt(8));
    const flow = screen.getByRole("complementary", { name: "Flow" });
    expect(within(flow).getByText("Photographed")).toBeInTheDocument();
    expect((await within(flow).findAllByAltText("Learn app home")).length).toBeGreaterThan(0);
  });

  it("grows a flow chain: the current step open with its inputs and outputs", () => {
    renderAt(replayAt(2));
    const flow = screen.getByRole("complementary", { name: "Flow" });
    expect(within(flow).getByText("Inputs")).toBeInTheDocument();
    expect(within(flow).getByText("Outputs")).toBeInTheDocument();
    expect(within(flow).getByText(/your inputs/)).toBeInTheDocument();
    expect(within(flow).getByText("→ used in Phase 3")).toBeInTheDocument();
    // Not reached yet: the later step has no card.
    expect(within(flow).queryByText("pdd-to-learn-app")).not.toBeInTheDocument();
  });

  it("folds earlier steps to one line once the replay moves on", () => {
    renderAt(replayAt(5));
    const flow = screen.getByRole("complementary", { name: "Flow" });
    const earlier = within(flow).getByRole("button", { name: /^idea-to-pdd/ });
    expect(earlier).toHaveAttribute("aria-expanded", "false");
    expect(within(earlier).getByText("1 in · 1 out")).toBeInTheDocument();
    // …but what it built stays on screen: the rail is where outputs live.
    expect(within(flow).getByRole("button", { name: /Turmeric Market Survey/ })).toBeInTheDocument();
    expect(within(flow).getByRole("button", { name: /pdd-to-learn-app/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("lands a decision only once its skill has finished", () => {
    const { container } = renderAt(replayAt(2));
    // Phase tiles count overridden decisions only; check the data path via the
    // phase panel instead — idea-to-design is open (the cursor's phase).
    expect(within(container).getByText("Question d1?")).toBeInTheDocument();
    expect(within(container).queryByText("Question d2?")).not.toBeInTheDocument();
  });
});

describe("PhaseView outside a replay", () => {
  const idle = () => replayAt(-1, { active: false, timeline: null });

  it("shows the WHOLE run as a flow, not just the open phase", async () => {
    renderAt(idle(), "/?phase=commcare-setup");
    const flow = screen.getByRole("complementary", { name: "Flow" });
    // Every phase, every step — the selected phase is marked, not isolated.
    expect(within(flow).getByRole("button", { name: /Phase 1 ·/ })).toBeInTheDocument();
    expect(within(flow).getByRole("button", { name: /Phase 3 ·/ })).toHaveAttribute("aria-current", "true");
    expect(within(flow).getByRole("button", { name: /^idea-to-pdd/ })).toBeInTheDocument();
    expect(within(flow).getByRole("button", { name: /^app-screenshot-capture/ })).toBeInTheDocument();
    // Each output under the step that built it, screenshots included.
    expect(within(flow).getByRole("button", { name: /Turmeric Market Survey/ })).toBeInTheDocument();
    // The app shows twice: under the step that built it, and under the
    // Phase 6 walk that photographed it.
    expect(within(flow).getAllByRole("button", { name: /Turmeric — FLW Training/ })).toHaveLength(2);
    expect((await within(flow).findAllByAltText("Learn app home")).length).toBeGreaterThan(0);
    expect(within(flow).getByText("Photographed")).toBeInTheDocument();
  });

  it("picks a phase on the left when its heading is clicked in the flow", () => {
    renderAt(idle(), "/?phase=commcare-setup");
    const flow = screen.getByRole("complementary", { name: "Flow" });
    fireEvent.click(within(flow).getByRole("button", { name: /Phase 1 ·/ }));
    expect(within(flow).getByRole("button", { name: /Phase 1 ·/ })).toHaveAttribute("aria-current", "true");
  });

  it("jumps from an input to the step that made it", async () => {
    renderAt(idle(), "/?phase=commcare-setup");
    const flow = screen.getByRole("complementary", { name: "Flow" });
    fireEvent.click(await within(flow).findByRole("button", { name: /^pdd-to-learn-app/ }));
    fireEvent.click(await within(flow).findByRole("button", { name: /Show where it was made/ }));
    await waitFor(() =>
      expect(within(flow).getByRole("button", { name: /^idea-to-pdd/ })).toHaveAttribute(
        "aria-expanded",
        "true",
      ),
    );
  });

  it("still shows what was built when the flow can't be loaded", async () => {
    vi.mocked(fetchRunFlow).mockRejectedValue(new Error("500"));
    renderAt(idle());
    const flow = screen.getByRole("complementary", { name: "Flow" });
    expect(await within(flow).findByText("inputs & outputs unavailable")).toBeInTheDocument();
    expect(within(flow).getAllByRole("button", { name: /Turmeric — FLW Training/ }).length).toBeGreaterThan(0);
  });
});
