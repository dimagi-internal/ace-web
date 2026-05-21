import { describe, expect, it } from "vitest";

import { parseTs, v2ToOppCard } from "../opps";

/**
 * Regression for #466.
 *
 * Before the fix, the backend serialised opps with no completed run as
 * ``updated_at: "1970-01-01T00:00:00Z"`` and the frontend mapper happily
 * propagated that into ``last_activity_at``. The OppCard then rendered
 * ``last 12/31/1969``. Now both sides treat null / missing / epoch-zero
 * as null.
 */
describe("parseTs (opp-card timestamp guard)", () => {
  it("returns null for null, undefined, empty string", () => {
    expect(parseTs(null)).toBeNull();
    expect(parseTs(undefined)).toBeNull();
    expect(parseTs("")).toBeNull();
  });

  it("returns null for non-string values", () => {
    expect(parseTs(0)).toBeNull();
    expect(parseTs(1)).toBeNull();
    expect(parseTs({})).toBeNull();
  });

  it("returns null for Unix epoch-zero variants (defends against stale payloads)", () => {
    expect(parseTs("1970-01-01T00:00:00Z")).toBeNull();
    expect(parseTs("1970-01-01T00:00:00.000Z")).toBeNull();
  });

  it("returns null for unparseable strings", () => {
    expect(parseTs("not-a-date")).toBeNull();
  });

  it("returns the original ISO string for valid timestamps", () => {
    expect(parseTs("2026-05-14T10:00:00Z")).toBe("2026-05-14T10:00:00Z");
  });
});

describe("v2ToOppCard", () => {
  it("maps null updated_at to null last_activity_at (no 1969 rendering)", () => {
    const card = v2ToOppCard({
      slug: "cosmetics-fgd-pilot",
      title: "Cosmetics FGD Pilot",
      current_phase: null,
      current_skill: null,
      run_count: 0,
      last_run_id: null,
      updated_at: null,
    });
    expect(card.last_activity_at).toBeNull();
    expect(card.created_at).toBeNull();
  });

  it("treats epoch-zero as null (stale cache defense)", () => {
    const card = v2ToOppCard({
      slug: "cosmetics-fgd-pilot",
      title: "Cosmetics FGD Pilot",
      run_count: 0,
      updated_at: "1970-01-01T00:00:00Z",
    });
    expect(card.last_activity_at).toBeNull();
  });

  it("passes valid ISO timestamps through unchanged", () => {
    const card = v2ToOppCard({
      slug: "opp-1",
      title: "Opp One",
      run_count: 3,
      updated_at: "2026-05-14T10:00:00Z",
    });
    expect(card.last_activity_at).toBe("2026-05-14T10:00:00Z");
  });
});
