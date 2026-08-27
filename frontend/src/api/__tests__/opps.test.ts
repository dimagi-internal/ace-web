import { describe, expect, it } from "vitest";

import { artifactBodyUrl, parseTs, v2ToOppCard } from "../opps";

/**
 * Regression for the Workbench artifact-preview 404.
 *
 * The ninja backend exposes raw artifact content ONLY at
 * `/api/w/{ws}/opps/{slug}/artifacts/{artifact_id}/download`. An earlier
 * (DRF-era) helper built `/steps/{skill}/artifacts/{name}`, a route the
 * backend never registered — so every step's artifact pane rendered a 404
 * (Django route miss). This locks the URL to the id-keyed download endpoint.
 */
describe("artifactBodyUrl (Workbench artifact preview)", () => {
  it("targets the id-keyed /artifacts/{id}/download endpoint, not /steps/*", () => {
    const url = artifactBodyUrl("dimagi-team", "hh-poverty-targeting", "20260722-1341", "drive-file-abc");
    expect(url).toContain("/api/w/dimagi-team/opps/hh-poverty-targeting/artifacts/drive-file-abc/download");
    expect(url).toContain("run_id=20260722-1341");
    expect(url).not.toContain("/steps/");
  });

  it("url-encodes the workspace, slug, and artifact id", () => {
    const url = artifactBodyUrl("ws space", "a/b", "r 1", "id/x");
    expect(url).toContain("/api/w/ws%20space/opps/a%2Fb/artifacts/id%2Fx/download");
    expect(url).toContain("run_id=r%201");
  });
});

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
