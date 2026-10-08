import { describe, expect, it } from "vitest";

import { isPlainViewer } from "@/api/oppSummary";

describe("isPlainViewer", () => {
  it("follows the server's `plain` when it sends one", () => {
    // A viewer-role member: may write, drawn the partner view.
    expect(isPlainViewer({ is_member: true, plain: true })).toBe(true);
    expect(isPlainViewer({ is_member: true, plain: false })).toBe(false);
  });

  it("falls back to 'not a member' for a payload that predates `plain`", () => {
    expect(isPlainViewer({ is_member: true })).toBe(false);
    expect(isPlainViewer({ is_member: false })).toBe(true);
    expect(isPlainViewer(undefined)).toBe(true);
  });
});
