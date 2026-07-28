import { describe, expect, it } from "vitest";
import { pageKeyFor } from "canopy-ui/presence";

import { acePresenceRules } from "../routes";

const key = (path: string) => pageKeyFor("ace", path, acePresenceRules);

describe("acePresenceRules", () => {
  it("groups every step of a run onto the run's key", () => {
    const step = key("/w/dimagi-team/opps/bednet/runs/run-001/steps/idea-to-pdd");
    const run = key("/w/dimagi-team/opps/bednet/runs/run-001");
    expect(step?.pageKey).toBe("ace:dimagi-team:opp:bednet/run-001");
    expect(step?.pageKey).toBe(run?.pageKey);
    expect(step?.subLocation).toBe("idea-to-pdd");
  });

  it("keeps a run-less opp separate from its runs", () => {
    expect(key("/w/dimagi-team/opps/bednet")?.pageKey).toBe("ace:dimagi-team:opp:bednet");
  });

  it("groups a video program run", () => {
    expect(key("/w/dimagi-team/videos/promo/runs/run-003")?.pageKey).toBe(
      "ace:dimagi-team:video:promo/run-003",
    );
  });

  it("gives list pages their own keys", () => {
    expect(key("/w/dimagi-team/opps")?.pageKey).toBe("ace:dimagi-team:opps");
    expect(key("/w/dimagi-team/activity")?.pageKey).toBe("ace:dimagi-team:activity");
    expect(key("/w/dimagi-team/videos")?.pageKey).toBe("ace:dimagi-team:videos");
  });

  it("puts workspace-agnostic pages in the global namespace", () => {
    expect(key("/settings")?.pageKey).toBe("ace:global:settings");
    expect(key("/system")?.pageKey).toBe("ace:global:system");
  });

  it("returns null for routes with no rule", () => {
    expect(key("/invite/abc123")).toBeNull();
  });

  it("distinguishes an opp compare page from a plain opp page", () => {
    expect(key("/w/dimagi-team/opps/compare/bednet/malaria")?.pageKey).toBe(
      "ace:dimagi-team:compare:bednet/malaria",
    );
  });

  it("collapses a video template editor onto its own key, not the program list", () => {
    expect(key("/w/dimagi-team/videos/templates/tpl-1")?.pageKey).toBe(
      "ace:dimagi-team:template:tpl-1",
    );
    expect(key("/w/dimagi-team/videos/templates")?.pageKey).toBe("ace:dimagi-team:videos-templates");
  });

  it("returns null for the public run-summary page (no /w/ prefix)", () => {
    expect(key("/opps/dimagi-team/bednet/runs/run-001/summary")).toBeNull();
  });
});
