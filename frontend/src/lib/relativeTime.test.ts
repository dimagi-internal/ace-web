import { describe, expect, it } from "vitest";

import { relativeTime } from "./relativeTime";

// Fixed "now" so the tests don't drift with the wall clock.
const NOW = new Date("2026-05-20T12:00:00Z").getTime();
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const MONTH = 30 * DAY;
const YEAR = 365 * DAY;

function isoAgo(ms: number): string {
  return new Date(NOW - ms).toISOString();
}

describe("relativeTime", () => {
  it("returns 'just now' for diffs under a minute", () => {
    expect(relativeTime(isoAgo(5_000), NOW)).toBe("just now");
    expect(relativeTime(isoAgo(59_000), NOW)).toBe("just now");
  });

  it("formats minutes", () => {
    expect(relativeTime(isoAgo(2 * MINUTE), NOW)).toBe("2m ago");
    expect(relativeTime(isoAgo(45 * MINUTE), NOW)).toBe("45m ago");
  });

  it("formats hours", () => {
    expect(relativeTime(isoAgo(3 * HOUR), NOW)).toBe("3h ago");
    expect(relativeTime(isoAgo(23 * HOUR), NOW)).toBe("23h ago");
  });

  it("formats 1 day in 'Nd ago' form", () => {
    expect(relativeTime(isoAgo(1 * DAY), NOW)).toBe("1d ago");
  });

  it("formats 10 days in 'Nd ago' form (regression for #487 — used to flip to absolute after 7d)", () => {
    expect(relativeTime(isoAgo(10 * DAY), NOW)).toBe("10d ago");
  });

  it("formats 29 days as days (still under 1 month)", () => {
    expect(relativeTime(isoAgo(29 * DAY), NOW)).toBe("29d ago");
  });

  it("formats 100 days in 'Nmo ago' form (no absolute fallback)", () => {
    expect(relativeTime(isoAgo(100 * DAY), NOW)).toBe("3mo ago");
    // Critical: must not contain a slash or absolute date marker.
    expect(relativeTime(isoAgo(100 * DAY), NOW)).not.toMatch(/[/]/);
  });

  it("formats 1000 days in 'Ny ago' form (no absolute fallback)", () => {
    expect(relativeTime(isoAgo(1000 * DAY), NOW)).toBe("2y ago");
    expect(relativeTime(isoAgo(1000 * DAY), NOW)).not.toMatch(/[/]/);
  });

  it("formats 400 days as '1y ago'", () => {
    expect(relativeTime(isoAgo(400 * DAY), NOW)).toBe("1y ago");
  });

  it("formats 6 months as '6mo ago'", () => {
    expect(relativeTime(isoAgo(6 * MONTH), NOW)).toBe("6mo ago");
  });

  it("never falls back to a locale-formatted absolute date for any magnitude", () => {
    // Cover small, medium, and large values. None should contain "/"
    // (toLocaleDateString) or ":" (toLocaleString).
    const samples = [
      30 * MINUTE,
      5 * HOUR,
      3 * DAY,
      30 * DAY,
      90 * DAY,
      500 * DAY,
      5 * YEAR,
    ];
    for (const ms of samples) {
      const out = relativeTime(isoAgo(ms), NOW);
      expect(out, `magnitude ${ms}ms produced an absolute date: ${out}`).toMatch(
        /^(just now|\d+m ago|\d+h ago|\d+d ago|\d+mo ago|\d+y ago)$/,
      );
    }
  });
});
