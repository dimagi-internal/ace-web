import { describe, expect, it } from "vitest";

import { clock, duration } from "../time";

describe("clock", () => {
  it("keeps a stable width below an hour so digits don't jitter", () => {
    expect(clock(0)).toBe("0:00");
    expect(clock(47)).toBe("0:47");
    expect(clock(754)).toBe("12:34");
  });

  it("pads minutes once hours appear", () => {
    expect(clock(3600)).toBe("1:00:00");
    expect(clock(15153)).toBe("4:12:33");
  });

  it("never renders a negative clock", () => {
    expect(clock(-5)).toBe("0:00");
  });
});

describe("duration", () => {
  it("renders an em dash rather than a zero it can't vouch for", () => {
    expect(duration(null)).toBe("—");
    expect(duration(undefined)).toBe("—");
  });

  it("scales the unit to the magnitude", () => {
    expect(duration(45)).toBe("45s");
    expect(duration(1620)).toBe("27m");
    expect(duration(22440)).toBe("6h 14m");
    expect(duration(7200)).toBe("2h");
  });
});
