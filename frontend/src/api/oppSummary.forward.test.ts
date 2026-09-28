import { describe, expect, it } from "vitest";

import { forwardedSummaryPath } from "./oppSummary";

describe("forwardedSummaryPath", () => {
  it("maps a redirected summary API URL to the summary page", () => {
    expect(
      forwardedSummaryPath(
        "https://labs.connect.dimagi.com/ace/api/opps/public/spark/spark-facilitator/runs/20260926-1413/summary",
        "/ace",
      ),
    ).toBe("/ace/opps/spark/spark-facilitator/runs/20260926-1413/summary");
  });

  it("keeps encoded segments encoded", () => {
    expect(forwardedSummaryPath("/api/opps/public/a%20b/c/runs/d/summary", "")).toBe(
      "/opps/a%20b/c/runs/d/summary",
    );
  });

  it("returns null for anything that is not a summary API URL", () => {
    expect(forwardedSummaryPath("https://x/ace/auth/login/", "/ace")).toBeNull();
  });
});
