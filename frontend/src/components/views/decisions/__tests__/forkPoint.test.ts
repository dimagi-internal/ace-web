import { describe, expect, it } from "vitest";

import type { Decision, PhaseInfo } from "@/api/types.ws";
import { computeForkPoint } from "../forkPoint";

const phases: PhaseInfo[] = [
  { name: "design", ordinal: 1, display_name: "Design" } as PhaseInfo,
  { name: "scenarios-and-acceptance", ordinal: 2, display_name: "Scenarios" } as PhaseInfo,
  { name: "ocs-setup", ordinal: 6, display_name: "OCS" } as PhaseInfo,
];

function dec(id: string, phase: string): Decision {
  return { id, phase, phase_raw: phase, skill: "x", question: "q", default: "v",
    options_considered: [], source: "x", status: "applied", notes: "" };
}

describe("computeForkPoint", () => {
  it("returns null when no edits", () => {
    expect(computeForkPoint({ decisions: [], edits: [], phases })).toBeNull();
  });

  it("returns the phase of a single edited row", () => {
    expect(computeForkPoint({
      decisions: [dec("a", "design")],
      edits: [{ row_id: "a", new_answer: "x" }],
      phases,
    })).toBe("design");
  });

  it("returns the lowest-ordinal phase across multiple edits", () => {
    expect(computeForkPoint({
      decisions: [dec("a", "design"), dec("b", "ocs-setup")],
      edits: [
        { row_id: "a", new_answer: "x" },
        { row_id: "b", new_answer: "y" },
      ],
      phases,
    })).toBe("design");
  });

  it("returns null when no edit row_id matches any decision", () => {
    expect(computeForkPoint({
      decisions: [dec("a", "design")],
      edits: [{ row_id: "ghost", new_answer: "x" }],
      phases,
    })).toBeNull();
  });

  it("ignores edits whose decision.phase isn't in the phases list", () => {
    expect(computeForkPoint({
      decisions: [dec("a", "unknown-phase")],
      edits: [{ row_id: "a", new_answer: "x" }],
      phases,
    })).toBeNull();
  });
});
