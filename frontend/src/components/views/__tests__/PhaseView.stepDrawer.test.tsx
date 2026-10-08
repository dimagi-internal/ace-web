/**
 * Step drill-down inside Phases — the job the retired Workbench tab used to
 * do. An open step (from the URL) shows its detail in the right column, beside
 * the phase it lives in; each skill row links to its own step address.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { OppSnapshot, Step } from "@/api/types.ws";
import type { Replay } from "@/components/replay/useReplay";

vi.mock("@/components/opps/StepDetailPane", () => ({
  StepDetailPane: (p: { skill: string; runId: string }) => (
    <div data-testid="step-detail">{`detail:${p.runId}:${p.skill}`}</div>
  ),
}));
vi.mock("@/components/opps/StepChatPane", () => ({
  StepChatPane: (p: { skill: string }) => <div data-testid="step-chat">{`chat:${p.skill}`}</div>,
}));
vi.mock("@/components/views/PhaseRail", () => ({
  PhaseRail: () => <aside aria-label="Flow" data-testid="phase-rail" />,
}));

const { PhaseView } = await import("../PhaseView");

function step(skill: string, phase: string, ordinal: number): Step {
  return {
    skill_name: skill, display_name: `${skill} name`, phase, phase_display: phase, ordinal,
    status: "complete", started_at: null, completed_at: null, error: null, has_judge: false,
    is_recurring: false, preview_text: "", judge: null, qa_result: null, artifacts: [],
  } as unknown as Step;
}

const SNAPSHOT = {
  opp: { slug: "opp", display_name: "Opp" },
  pdd_body: "",
  runs: [{ run_id: "r9", last_actor_at: null }],
  selected_run_id: "r9",
  phases: [
    { name: "idea-to-design", display_name: "Idea to design", ordinal: 1, agent: "a" },
    { name: "commcare-setup", display_name: "CommCare setup", ordinal: 3, agent: "b" },
  ],
  current_run: {
    run_id: "r9", mode: "auto", status: "complete", started_at: null, completed_at: null,
    current_phase: null, current_step: null, skill_versions: {}, notes: "",
    steps: [step("idea-to-pdd", "idea-to-design", 1), step("pdd-to-learn-app", "commcare-setup", 2)],
    decisions: [],
    products: [],
  },
} as unknown as OppSnapshot;

const noop = () => {};
const OFF: Replay = {
  active: false, loading: false, error: null, timeline: null,
  beat: { phase: null, skill: null, index: -1 },
  reveal: { done: new Set(), running: new Set(), phases: new Set() }, total: 0, playing: false,
  start: noop, stop: noop, toggle: noop, next: noop, prev: noop, restart: noop, goTo: noop,
  goToSkill: noop, goToPhase: () => false, hold: noop,
} as unknown as Replay;
const ON: Replay = { ...OFF, active: true } as Replay;

const stepHref = (skill: string, phase: string) => `/w/ws/opps/opp/runs/r9/steps/${skill}?phase=${phase}`;
let onCloseStep: ReturnType<typeof vi.fn>;

function renderView(openSkill: string | null, replay: Replay = OFF, path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <PhaseView
        snapshot={SNAPSHOT}
        oppSlug="opp"
        workspaceSlug="ws"
        replay={replay}
        openSkill={openSkill}
        stepHref={stepHref}
        onCloseStep={onCloseStep}
      />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  onCloseStep = vi.fn();
  // The panel's side fetches (skill products) are not under test.
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
});
afterEach(() => vi.unstubAllGlobals());

describe("PhaseView step drill-down", () => {
  it("shows the open step's detail beside its phase, in place of the flow rail", () => {
    renderView("pdd-to-learn-app");
    const drawer = screen.getByRole("complementary", { name: "Step: pdd-to-learn-app name" });
    expect(within(drawer).getByTestId("step-detail")).toHaveTextContent(
      "detail:r9:pdd-to-learn-app",
    );
    expect(screen.queryByTestId("phase-rail")).not.toBeInTheDocument();
    // The step link named no phase: the step's own phase is opened.
    expect(screen.getByRole("heading", { name: "CommCare setup" })).toBeInTheDocument();
  });

  it("keeps the flow rail when no step is open", () => {
    renderView(null);
    expect(screen.getByTestId("phase-rail")).toBeInTheDocument();
    expect(screen.queryByTestId("step-detail")).not.toBeInTheDocument();
  });

  it("has the step's chats one tab away", () => {
    renderView("idea-to-pdd");
    fireEvent.click(screen.getByRole("button", { name: "Chat" }));
    expect(screen.getByTestId("step-chat")).toHaveTextContent("chat:idea-to-pdd");
  });

  it("closes from its close button and from Esc", () => {
    renderView("idea-to-pdd");
    fireEvent.click(screen.getByRole("button", { name: "Close step" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCloseStep).toHaveBeenCalledTimes(2);
  });

  it("closes the step when another phase is picked, landing on that phase", () => {
    renderView("idea-to-pdd");
    fireEvent.click(screen.getByRole("button", { name: /CommCare setup/ }));
    expect(onCloseStep).toHaveBeenCalledWith("commcare-setup");
  });

  it("links each skill row to its own step address", () => {
    renderView(null, OFF, "/?phase=idea-to-design");
    fireEvent.click(screen.getByRole("button", { name: /idea-to-pdd name/ }));
    expect(screen.getByRole("link", { name: /Open details/ })).toHaveAttribute(
      "href",
      "/w/ws/opps/opp/runs/r9/steps/idea-to-pdd?phase=idea-to-design",
    );
  });

  it("opens no step during a replay — its detail is the run's final state", () => {
    renderView("idea-to-pdd", ON);
    expect(screen.queryByTestId("step-detail")).not.toBeInTheDocument();
  });
});
