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
    // `~global`, not `global`: the leading `~` cannot match the backend's
    // WORKSPACE_RE, so no real workspace slug can shadow the sentinel and
    // skip the membership gate. Cross-app contract with
    // apps/presence/keys.py::GLOBAL_SENTINEL and canopy-web.
    expect(key("/settings")?.pageKey).toBe("ace:~global:settings");
    expect(key("/system")?.pageKey).toBe("ace:~global:system");
  });

  it("never throws on a malformed percent-escape in the path", () => {
    // Regression: `decodeURIComponent("100%")` raises URIError. This runs
    // during render in TopNav, above the router's Outlet, in an SPA with no
    // error boundary — an unguarded decode blanks the whole app.
    const step = () => key("/w/ws/opps/o/runs/r/steps/100%");
    expect(step).not.toThrow();
    expect(step()?.pageKey).toBe("ace:ws:opp:o/r");
    expect(step()?.subLocation).toBe("100%");
  });

  it("still decodes a WELL-formed percent-escape", () => {
    expect(key("/w/ws/opps/o/runs/r/steps/idea%20to%20pdd")?.subLocation).toBe("idea to pdd");
  });

  it("does not collapse a program slug that merely starts with a gallery name", () => {
    // Regression for an unanchored /videos/(library|templates)/ rule:
    // `library-x` is a real program, not the gallery. (`librarian` does NOT
    // hit this rule — `/videos/([^/]+)` catches it first only because the
    // gallery rule is listed earlier, so use the hyphenated form.)
    expect(key("/w/ws/videos/library-x")?.pageKey).toBe("ace:ws:video:library-x");
    expect(key("/w/ws/videos/templates-archive")?.pageKey).toBe("ace:ws:video:templates-archive");
    // ...while the galleries themselves still resolve, with and without a
    // trailing slash.
    expect(key("/w/ws/videos/library")?.pageKey).toBe("ace:ws:videos-library");
    expect(key("/w/ws/videos/library/")?.pageKey).toBe("ace:ws:videos-library");
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
