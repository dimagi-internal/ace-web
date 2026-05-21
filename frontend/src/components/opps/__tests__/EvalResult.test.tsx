import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvalResult } from "@/components/opps/EvalResult";
import type { Judge } from "@/api/types.ws";

// Pin the canonical "Eval" terminology for the LLM-judge scoring concept.
// Regression test for issue #488 — UI must say "Eval" everywhere, not
// "Judge" or "Verdict".
describe("EvalResult — canonical 'Eval' terminology (issue #488)", () => {
  it("renders 'Eval' label and no eval message when there is no judge data", () => {
    const { container } = render(<EvalResult judge={null} />);
    // The empty-state message uses "Eval" + "no eval for this step".
    expect(screen.getByText(/Eval/)).toBeInTheDocument();
    expect(screen.getByText(/no eval for this step/i)).toBeInTheDocument();
    // And specifically does NOT use the legacy "Judge" or "Verdict" terms.
    expect(container.textContent ?? "").not.toMatch(/Judge/);
    expect(container.textContent ?? "").not.toMatch(/Verdict/);
    expect(container.textContent ?? "").not.toMatch(/NO LLM JUDGE/);
  });

  it("renders 'Eval' header label when judge data is present", () => {
    const judge: Judge = {
      score: 8.5,
      score_pct: 85,
      passed: true,
      evaluated_at: "2026-05-21T00:00:00Z",
      criteria: { clarity: 9, accuracy: 8 },
      rationale: "Solid work overall.",
    };
    const { container } = render(<EvalResult judge={judge} />);
    // The pane label must say "Eval", not "Judge".
    expect(screen.getByText("Eval")).toBeInTheDocument();
    // Score should be rendered.
    expect(screen.getByText("85/100")).toBeInTheDocument();
    // Regression guard against the old labels.
    expect(container.textContent ?? "").not.toMatch(/Judge/);
    expect(container.textContent ?? "").not.toMatch(/Verdict/);
  });
});
