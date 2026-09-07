import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/**
 * The OCS chat widget is pinned by version in OcsWidgetMount, and OCS retires
 * old rungs on a published schedule. From
 * dimagi/open-chat-studio `apps/channels/widget_versions.py`:
 *
 *     DEPRECATIONS = [WidgetDeprecation(below_version="0.6.0",
 *                                       sunset_at=datetime(2026, 10, 1, UTC))]
 *
 * This mount sat at 0.5.3 — below that floor, sunsetting 2026-10-01 — and
 * nothing here noticed, because a pinned version has no failure mode until the
 * day it stops being served. The run-summary page is un-authed and the widget is
 * the one thing on it an outsider can use without being granted anything, so it
 * going dark leaves the page inviting people to ask questions of a dead bubble.
 *
 * This test reads the source rather than importing the component: the assertion
 * is about the literal shipped in the bundle, and a render test would pass just
 * as happily against an expired pin.
 */
// Resolved from the vitest root (frontend/) rather than import.meta.url, which
// is not a file: URL under the jsdom transform.
const SOURCE = readFileSync(
  resolve(process.cwd(), "src/components/opps/summary/OcsWidgetMount.tsx"),
  "utf8",
);

/** OCS's current `below_version` floor. Raise BOTH when OCS raises theirs. */
const OCS_DEPRECATION_FLOOR = "0.6.0";

function pinnedVersion(): string {
  // Anchored to the destructured default in the component signature, NOT a bare
  // /version = "x"/ — the file's own doc comment quotes OCS's
  // `below_version="0.6.0"`, and a loose regex matches that instead, reads the
  // floor as the pin, and passes against any expired version. (It did.)
  const m = SOURCE.match(/export function OcsWidgetMount\([^)]*version\s*=\s*"([\d.]+)"/);
  if (!m) throw new Error("could not find the pinned widget version in OcsWidgetMount.tsx");
  return m[1];
}

function cmp(a: string, b: string): number {
  const pa = a.split(".").map(Number);
  const pb = b.split(".").map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d;
  }
  return 0;
}

describe("OcsWidgetMount version pin", () => {
  it("is at or above OCS's published deprecation floor", () => {
    expect(cmp(pinnedVersion(), OCS_DEPRECATION_FLOOR)).toBeGreaterThanOrEqual(0);
  });

  it("loads the widget from the same host OCS serves it from", () => {
    // OCS's widget_script_url() emits unpkg.com. `www.unpkg.com` also resolves
    // today, but matching the upstream host exactly keeps one fewer thing to
    // re-derive if unpkg ever treats them differently.
    expect(SOURCE).toContain("https://unpkg.com/open-chat-studio-widget@");
    expect(SOURCE).not.toContain("www.unpkg.com");
  });

  it("passes the attributes OCS's own embed template uses", () => {
    // templates/experiments/share/widget.html at HEAD, non-OAuth branch.
    for (const attr of ["chatbot-id", "embed-key", "button-text", "position", "visible"]) {
      expect(SOURCE).toContain(attr);
    }
  });
});
