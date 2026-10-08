import { describe, expect, it } from "vitest";

import type { PublicDecisionEdit, ReviewDecision } from "@/api/oppSummary";
import { isStatement } from "@/components/opps/summary/DecisionsReview";

const row = (over: Partial<ReviewDecision> = {}) =>
  ({
    id: "r",
    status: "ai-default",
    question: "How many facilitators?",
    ai_default: "12",
    options_considered: ["12"],
    ...over,
  }) as ReviewDecision;

describe("isStatement", () => {
  it("is a row ACE stated as a sentence, with no answer beside it", () => {
    expect(isStatement(row({ plain: "About 12 facilitators, one per community." }))).toBe(true);
  });

  it("is not a question row", () => {
    expect(isStatement(row())).toBe(false);
    expect(isStatement(row({ plain_question: "How many facilitators?", plain: "About 12." }))).toBe(
      false,
    );
  });

  it("is not a stated row a person has changed — the change is shown beside it", () => {
    const edit = { override: "15", is_revert: false } as PublicDecisionEdit;
    expect(isStatement(row({ plain: "About 12 facilitators." }), edit)).toBe(false);
  });

  it("is never a replaced row", () => {
    expect(isStatement(row({ plain: "About 12.", superseded_by: "x" }))).toBe(false);
  });
});
