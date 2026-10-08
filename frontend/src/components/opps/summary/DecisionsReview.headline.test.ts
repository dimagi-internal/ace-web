import { describe, expect, it } from "vitest";

import type { ReviewDecision } from "@/api/oppSummary";
import {
  decisionBreakdown,
  decisionsHeadline,
  decisionsTabBadge,
} from "@/components/opps/summary/DecisionsReview";

const row = (id: string, over: Partial<ReviewDecision> = {}) =>
  ({ id, status: "ai-default", ...over }) as ReviewDecision;

describe("decisionBreakdown / decisionsHeadline", () => {
  // The spark/20261004-1706 shape: 120 live rows = 25 asks + 6 deferred + 89 calls.
  const rows = [
    ...Array.from({ length: 25 }, (_, i) => row(`c${i}`, { review_ask: "recommended-confirmation" })),
    ...Array.from({ length: 6 }, (_, i) => row(`d${i}`, { status: "deferred" })),
    ...Array.from({ length: 89 }, (_, i) => row(`a${i}`)),
    row("gone", { superseded_by: "a0", review_ask: "recommended-confirmation" }),
  ];

  it("splits the live rows into parts that add up to the total", () => {
    const b = decisionBreakdown(rows, {});
    expect(b).toMatchObject({ deferred: 6, byAce: 89, total: 120 });
    expect(b.confirm).toEqual({ total: 25, outstanding: 25 });
    expect(b.confirm.total + b.answer.total + b.deferred + b.byAce).toBe(b.total);
  });

  it("reads asks first", () => {
    const h = decisionsHeadline(decisionBreakdown(rows, {}));
    expect(h.lead).toBe("25 to confirm");
    expect(h.rest).toEqual(["6 deferred", "89 decided by ACE (for review)"]);
  });

  it("says how many are left once some are answered", () => {
    const h = decisionsHeadline(
      decisionBreakdown(rows, { c0: { confirmed: true } as never, c1: { confirmed: true } as never }),
    );
    expect(h.lead).toBe("23 of 25 still to confirm");
  });

  it("names both kinds of ask", () => {
    const h = decisionsHeadline(
      decisionBreakdown([row("c", { review_ask: "recommended-confirmation" }), row("q", { review_ask: "required-before" })], {}),
    );
    expect(h.lead).toBe("1 to confirm · 1 to answer");
  });

  it("has no lead when nothing is asked", () => {
    const h = decisionsHeadline(decisionBreakdown([row("a"), row("b")], {}));
    expect(h.lead).toBeNull();
    expect(h.rest).toEqual(["2 decided by ACE (for review)"]);
  });
});

describe("decisionsTabBadge", () => {
  const t = (c: number, a: number) =>
    decisionsTabBadge({ confirm: { outstanding: c }, answer: { outstanding: a } });
  it("carries what is waiting on the reader", () => {
    expect(t(25, 0)).toBe("25 to confirm");
    expect(t(0, 2)).toBe("2 to answer");
    expect(t(25, 2)).toBe("27 for you");
    expect(t(0, 0)).toBeUndefined();
  });
});
