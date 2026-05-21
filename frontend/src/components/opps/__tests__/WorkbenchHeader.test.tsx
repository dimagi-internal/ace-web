import { describe, expect, it } from "vitest";

import { openDecisionsLabel } from "../WorkbenchHeader";

// Issue #486 — the open-decisions chip used to render "{n} open" as the
// visible label while its ARIA label said "{n} open decisions — jump to
// Phases". The mismatch hid the noun from sighted users. Pin the label
// across the boundary counts so a future "let's simplify the chip" PR
// can't quietly drop the noun again.
describe("openDecisionsLabel", () => {
  it("hides the chip but keeps the helper safe for 0", () => {
    // The chip itself isn't rendered for 0 (see decisionsSummary.open > 0
    // guard in WorkbenchHeader). The helper still returns a sensible plural
    // form so test fixtures / Storybook / future callers don't blow up.
    expect(openDecisionsLabel(0)).toBe("0 open decisions");
  });

  it("uses the singular noun for exactly 1", () => {
    expect(openDecisionsLabel(1)).toBe("1 open decision");
  });

  it("uses the plural noun for 2", () => {
    expect(openDecisionsLabel(2)).toBe("2 open decisions");
  });

  it("uses the plural noun for 5", () => {
    expect(openDecisionsLabel(5)).toBe("5 open decisions");
  });

  it("drops the legacy '— jump to Phases' suffix", () => {
    // The pre-fix ARIA label leaked an interaction hint that was already
    // implied by the chip being a button. Make sure the helper never
    // re-introduces it (regardless of count).
    for (const n of [1, 2, 5, 12]) {
      expect(openDecisionsLabel(n)).not.toContain("jump to Phases");
      expect(openDecisionsLabel(n)).not.toContain("—");
    }
  });
});
