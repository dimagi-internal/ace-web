import { describe, expect, it } from "vitest";

import type { Decision } from "@/api/types.ws";
import {
  answerChannelLabel,
  asksAnswer,
  asksConfirmation,
  isReviewAsk,
  neededByPhrase,
  ownerLabel,
} from "@/components/opps/decisions/decisionDisplay";

const base: Decision = {
  id: "d",
  phase: "idea-to-design",
  phase_raw: "1-design",
  skill: "idea-to-pdd",
  question: "q",
  ai_default: "a",
  override: "",
  options_considered: [],
  source: "",
  status: "ai-default",
  notes: "",
  override_reasoning: "",
  evidence_basis: "stated",
  conflict_signals: [],
};

describe("review asks (ACE spec 2026-10-04)", () => {
  it("tells the two kinds of ask apart, and never asks on a deferred or replaced row", () => {
    const confirm = { ...base, review_ask: "recommended-confirmation" };
    const answer = { ...base, review_ask: "required-before", needed_by: "award" };
    expect(asksConfirmation(confirm) && !asksAnswer(confirm)).toBe(true);
    expect(asksAnswer(answer) && !asksConfirmation(answer)).toBe(true);
    expect(isReviewAsk({ ...answer, status: "deferred" })).toBe(false);
    expect(isReviewAsk({ ...confirm, superseded_by: "x" })).toBe(false);
  });

  it("phrases needed_by, owner and answer_channel for a reader", () => {
    expect(neededByPhrase("award")).toBe("before an implementing organisation is chosen");
    expect(neededByPhrase("go-live")).toBe("before go-live");
    expect(neededByPhrase("")).toBe("before launch");
    expect(ownerLabel("implementing-org")).toBe("The implementing organisation");
    expect(ownerLabel("Spark M&E")).toBe("Spark M&E");
    expect(answerChannelLabel("review")).toBe("Here, on this page");
    expect(answerChannelLabel("call")).toBe("On a call with Dimagi");
    expect(answerChannelLabel("solicitation:q-7")).toMatch(
      /^Through the call for implementing organisations/,
    );
    expect(answerChannelLabel("solicitation:q-7")).not.toMatch(/q-7/);
    expect(answerChannelLabel("solicitation:q-7", true)).toMatch(/\(question q-7\)$/);
  });
});
