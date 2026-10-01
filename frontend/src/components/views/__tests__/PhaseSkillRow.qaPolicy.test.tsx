/**
 * The QA surface says what the plugin DECIDED for a producer
 * (skills/_qa-decisions.md), not "missing" for every step without its own
 * `-qa` skill — and flags the two real gaps loudly.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { QaPolicy, Step } from "@/api/types.ws";

import { ChecksLine, isQuietChecks, QASection } from "../phase-skill/sections";

function step(over: Partial<Step> = {}): Step {
  return {
    skill_name: "connect-opp-setup", display_name: "Connect Opportunity Setup",
    phase: "connect-setup", phase_display: "Connect setup", ordinal: 1, status: "complete",
    started_at: null, completed_at: null, error: null, has_judge: false, is_recurring: false,
    preview_text: "", judge: null, qa_result: null, artifacts: [],
    ...over,
  } as Step;
}
const policy = (status: QaPolicy["status"], reason = "Because reasons.") =>
  ({ status, label: status, reason }) as QaPolicy;

describe("QA decisions on the Phases screen", () => {
  it("a step with no QA by design and no eval gets one quiet line with the reason", () => {
    const s = step({ qa_policy: policy("none", "Connect MCP atoms validate at boundary.") });
    expect(isQuietChecks(s)).toBe(true);
    render(<ChecksLine step={s} />);
    expect(screen.getByText(/QA: none, by design · Eval: none for this step/)).toBeInTheDocument();
    expect(screen.getByText("Connect MCP atoms validate at boundary.")).toBeInTheDocument();
  });

  it("an inline-QA step says it checks itself", () => {
    render(<QASection step={step({ qa_policy: policy("inline") })} />);
    expect(screen.getByText("QA: checked inside the step")).toBeInTheDocument();
  });

  it("a step whose QA skill recorded nothing is flagged, not hidden", () => {
    const s = step({ qa_policy: policy("standalone") });
    expect(isQuietChecks(s)).toBe(false);
    render(<QASection step={s} />);
    expect(screen.getByText("No result recorded")).toBeInTheDocument();
  });

  it("a QA pass that ran zero checks is a warning, not a pass", () => {
    const s = step({
      qa_result: {
        skill: "demo-data-setup-qa", verdict: "pass", failures: [], auto_fix: null,
        stats: { checks_run: 0, checks_passed: 0, checks_failed: 0 },
      } as unknown as Step["qa_result"],
    });
    render(<QASection step={s} />);
    expect(screen.getByText("Ran no checks — nothing was verified")).toBeInTheDocument();
  });
});
