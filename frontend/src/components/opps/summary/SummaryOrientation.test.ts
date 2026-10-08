import { describe, expect, it } from "vitest";

import { programWorkerNoun } from "@/components/opps/summary/SummaryOrientation";

describe("programWorkerNoun", () => {
  it("finds the program's own word for its worker, plural or not", () => {
    expect(programWorkerNoun("About 12 facilitators record each meeting.")).toBe("facilitator");
    expect(programWorkerNoun("A community health worker visits each home.")).toBe(
      "community health worker",
    );
  });

  it("guesses nothing from a near-miss or an empty description", () => {
    expect(programWorkerNoun("Verified community-meeting facilitation.")).toBeNull();
    expect(programWorkerNoun("")).toBeNull();
    expect(programWorkerNoun(null)).toBeNull();
  });
});
