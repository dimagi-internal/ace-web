import { describe, expect, it } from "vitest";

import { humanizeSkill } from "../ViewerContext";

describe("humanizeSkill", () => {
  it("reads a paired QA/eval skill or the orchestrator like the rest of the screen", () => {
    expect(humanizeSkill("idea-to-pdd-qa")).toBe("Idea to PDD QA");
    expect(humanizeSkill("ace-orchestrator")).toBe("ACE orchestrator");
    expect(humanizeSkill("app-ux-eval")).toBe("App UX eval");
  });
});
