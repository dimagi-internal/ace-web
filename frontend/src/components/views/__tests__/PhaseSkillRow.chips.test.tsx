import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { Decision, Step } from "@/api/types.ws";

import { PhaseSkillRow } from "../PhaseSkillRow";

function step(p: Partial<Step> = {}): Step {
  return {
    skill_name: "training-flw-guide",
    display_name: "FLW Training Guide",
    phase: "qa-and-training",
    phase_display: "QA & Training",
    ordinal: 1,
    status: "complete",
    started_at: null,
    completed_at: null,
    error: null,
    has_judge: true,
    is_recurring: false,
    preview_text: "",
    judge: null,
    qa_result: null,
    artifacts: [],
    ...p,
  };
}

const renderRow = (props: Partial<Parameters<typeof PhaseSkillRow>[0]> = {}) =>
  render(
    <MemoryRouter>
      <PhaseSkillRow step={step()} oppSlug="opp" runId="r1" {...props} />
    </MemoryRouter>,
  );

describe("eval chip on a step with no score", () => {
  it("says 'no score' on a finished run — never an eternal hourglass", () => {
    renderRow();
    expect(screen.getByText("no score")).toBeInTheDocument();
    expect(screen.queryByText("⏳")).not.toBeInTheDocument();
  });

  it("keeps the hourglass while the run is live and the eval may still land", () => {
    renderRow({ runLive: true });
    expect(screen.getByText("⏳")).toBeInTheDocument();
  });

  it("keeps the hourglass for a step that is still running", () => {
    renderRow({ step: step({ status: "running" }) });
    expect(screen.getByText("⏳")).toBeInTheDocument();
  });
});

describe("decisions in the drawer", () => {
  const decision: Decision = {
    id: "d1",
    phase: "qa-and-training",
    phase_raw: "6-qa-and-training",
    skill: "training-flw-guide",
    question: "Visit cadence?",
    ai_default: "weekly",
    override: "fortnightly",
    options_considered: [],
    source: "",
    status: "overridden",
    notes: "",
    override_reasoning: "",
    evidence_basis: "stated",
    conflict_signals: [],
  } as unknown as Decision;

  it("shows what was decided and that a person overrode it", () => {
    renderRow({ decisions: [decision], autoOpen: true });
    expect(screen.getByText("Visit cadence?")).toBeInTheDocument();
    expect(screen.getByText("fortnightly")).toBeInTheDocument();
    expect(screen.getByText(/overridden · AI said/)).toBeInTheDocument();
  });
});

it("underlines glossary terms in the skill name", () => {
  const { container } = renderRow();
  expect(container.querySelector("abbr")?.textContent).toBe("FLW");
});
