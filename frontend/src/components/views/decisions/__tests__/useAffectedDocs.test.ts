import { describe, expect, it } from "vitest";

import type { Decision } from "@/api/types.ws";
import type { EditOp } from "../decisionsReducer";
import { computeAffectedDocs } from "../useAffectedDocs";

function dec(id: string, skill: string): Decision {
  return {
    id,
    phase: "design",
    phase_raw: "design",
    skill,
    question: `q-${id}`,
    ai_default: "v",
    override: "",
    options_considered: [],
    // `source` is a free-text description in the wire schema (not a skill
    // slug). Set it to something obviously non-skill so a regression that
    // mistakenly keys the crosswalk off `source` will return no products.
    source: `description for ${id}`,
    status: "ai-default",
    notes: "",
  };
}

const products: Record<string, string[]> = {
  "idea-to-pdd": ["1-design/idea-to-pdd.md"],
  "pdd-to-work-order": ["1-design/pdd-to-work-order.gdoc"],
};

describe("computeAffectedDocs", () => {
  it("returns empty when no edits", () => {
    const out = computeAffectedDocs({
      decisions: [dec("a", "idea-to-pdd")],
      edits: [],
      skillProducts: products,
    });
    expect(out).toEqual([]);
  });

  it("returns paths for the source skills of edited rows", () => {
    const decisions = [dec("a", "idea-to-pdd"), dec("b", "pdd-to-work-order")];
    const edits: EditOp[] = [
      { row_id: "a", new_answer: "x" },
      { row_id: "b", new_answer: "y" },
    ];
    const out = computeAffectedDocs({ decisions, edits, skillProducts: products });
    expect(out.sort()).toEqual([
      "1-design/idea-to-pdd.md",
      "1-design/pdd-to-work-order.gdoc",
    ]);
  });

  it("deduplicates when two edited rows share a source skill", () => {
    const decisions = [dec("a", "idea-to-pdd"), dec("b", "idea-to-pdd")];
    const edits: EditOp[] = [
      { row_id: "a", new_answer: "x" },
      { row_id: "b", new_answer: "y" },
    ];
    const out = computeAffectedDocs({ decisions, edits, skillProducts: products });
    expect(out).toEqual(["1-design/idea-to-pdd.md"]);
  });

  it("ignores edits whose row_id isn't in decisions", () => {
    const out = computeAffectedDocs({
      decisions: [dec("a", "idea-to-pdd")],
      edits: [{ row_id: "ghost", new_answer: "x" }],
      skillProducts: products,
    });
    expect(out).toEqual([]);
  });

  it("falls back gracefully when a source skill isn't in the products map", () => {
    const decisions = [dec("a", "unknown-skill")];
    const edits: EditOp[] = [{ row_id: "a", new_answer: "x" }];
    const out = computeAffectedDocs({ decisions, edits, skillProducts: products });
    expect(out).toEqual([]);
  });
});
