import { describe, expect, it } from "vitest";

import type { Decision } from "@/api/types.ws";
import { buildDecisionOverridesExport } from "../localExport";

function dec(over: Partial<Decision> = {}): Decision {
  return {
    id: "row-1",
    phase: "design",
    phase_raw: "design",
    skill: "idea-to-pdd",
    question: "Who is the target population?",
    ai_default: "Kenya",
    override: "",
    options_considered: ["Kenya", "Tanzania"],
    source: "idea-to-pdd",
    status: "ai-default",
    notes: "",
    override_reasoning: "",
    evidence_basis: "stated",
    conflict_signals: [],
    ...over,
  };
}

describe("buildDecisionOverridesExport", () => {
  it("joins buffered edits with decision context, mirroring the Drive file shape", () => {
    const doc = buildDecisionOverridesExport({
      oppSlug: "my-opp",
      runId: "run-1",
      edits: [
        {
          row_id: "row-1",
          new_answer: "Tanzania",
          override_reasoning: "LLO confirmed",
          editor_email: "expert@partner.org",
        },
      ],
      decisions: [dec()],
    });

    expect(doc.kind).toBe("decision-overrides-local-export");
    expect(doc.opp).toBe("my-opp");
    expect(doc.exported_at).toBeTruthy();
    expect(doc.overrides).toHaveLength(1);
    expect(doc.overrides[0]).toMatchObject({
      id: "row-1",
      phase: "design",
      question: "Who is the target population?",
      ai_default: "Kenya",
      override: "Tanzania",
      override_reasoning: "LLO confirmed",
      decided_by: "expert@partner.org",
      source_run_id: "run-1",
    });
  });

  it("keeps buffered edits whose row is missing from decisions — locally true beats joinable", () => {
    const doc = buildDecisionOverridesExport({
      oppSlug: "my-opp",
      runId: "run-1",
      edits: [{ row_id: "ghost-row", new_answer: "whatever" }],
      decisions: [dec()],
    });

    expect(doc.overrides).toHaveLength(1);
    expect(doc.overrides[0]).toMatchObject({
      id: "ghost-row",
      override: "whatever",
    });
  });

  it("returns an empty overrides list for an empty buffer", () => {
    const doc = buildDecisionOverridesExport({
      oppSlug: "my-opp",
      runId: "run-1",
      edits: [],
      decisions: [dec()],
    });
    expect(doc.overrides).toEqual([]);
  });
});
