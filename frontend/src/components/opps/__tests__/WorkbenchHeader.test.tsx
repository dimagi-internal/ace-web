import { describe, expect, it } from "vitest";

import { overriddenDecisionsLabel } from "../WorkbenchHeader";

describe("overriddenDecisionsLabel", () => {
  it("uses the singular noun for exactly 1", () => {
    expect(overriddenDecisionsLabel(1)).toBe("1 overridden decision");
  });

  it("uses the plural noun for 2", () => {
    expect(overriddenDecisionsLabel(2)).toBe("2 overridden decisions");
  });

  it("uses the plural noun for 5", () => {
    expect(overriddenDecisionsLabel(5)).toBe("5 overridden decisions");
  });
});
