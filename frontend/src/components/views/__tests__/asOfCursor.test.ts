import { describe, expect, it } from "vitest";

import type { Step } from "@/api/types.ws";
import { asOfCursor } from "../PhaseView";

const FINISHED: Step = {
  skill_name: "idea-to-pdd",
  display_name: "Idea to PDD",
  phase: "idea-to-design",
  phase_display: "Design",
  ordinal: 1,
  status: "complete",
  started_at: "2026-07-22T13:41:00Z",
  completed_at: "2026-07-22T14:11:00Z",
  error: null,
  has_judge: true,
  is_recurring: false,
  preview_text: "A 12-page programme design document.",
  judge: { score: 8, score_pct: 88, passed: true } as Step["judge"],
  qa_result: { verdict: "pass" } as Step["qa_result"],
  artifacts: [{ name: "pdd.md" } as Step["artifacts"][number]],
};

describe("asOfCursor", () => {
  it("withholds everything the run hadn't produced yet", () => {
    const before = asOfCursor(FINISHED, false);
    // The ending must not be visible ahead of the playhead.
    expect(before.judge).toBeNull();
    expect(before.qa_result).toBeNull();
    expect(before.artifacts).toEqual([]);
    expect(before.preview_text).toBe("");
    expect(before.error).toBeNull();
    expect(before.completed_at).toBeNull();
  });

  it("keeps identity so the row is still recognisable", () => {
    const before = asOfCursor(FINISHED, false);
    expect(before.skill_name).toBe("idea-to-pdd");
    expect(before.display_name).toBe("Idea to PDD");
    expect(before.phase).toBe("idea-to-design");
    expect(before.ordinal).toBe(1);
    expect(before.has_judge).toBe(true);
  });

  it("marks a step the cursor is inside as running", () => {
    expect(asOfCursor(FINISHED, true).status).toBe("running");
    expect(asOfCursor(FINISHED, false).status).toBe("pending");
  });

  it("withholds a FAILING verdict too, not just a passing one", () => {
    const failed: Step = {
      ...FINISHED,
      status: "judge-fail",
      judge: { score: 2, score_pct: 22, passed: false } as Step["judge"],
      error: "boom",
    };
    const before = asOfCursor(failed, false);
    expect(before.judge).toBeNull();
    expect(before.error).toBeNull();
    expect(before.status).toBe("pending");
  });

  it("does not mutate the step it was given", () => {
    const copy = { ...FINISHED };
    asOfCursor(FINISHED, false);
    expect(FINISHED).toEqual(copy);
    expect(FINISHED.artifacts).toHaveLength(1);
  });
});
