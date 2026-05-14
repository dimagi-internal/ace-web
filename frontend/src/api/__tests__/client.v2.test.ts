import { describe, expect, it } from "vitest";
import { apiV2 } from "../client.v2";
import type { components } from "../generated";

describe("apiV2 typed client", () => {
  it("compiles with typed paths", () => {
    type OppCardOut = components["schemas"]["OppCardOut"];
    const sample: OppCardOut = {
      slug: "x",
      title: "x",
      run_count: 0,
      updated_at: "2026-05-14T00:00:00Z",
    };
    expect(sample.slug).toBe("x");
  });

  it("apiV2 client is created", () => {
    expect(apiV2).toBeDefined();
    expect(typeof apiV2.GET).toBe("function");
    expect(typeof apiV2.POST).toBe("function");
  });
});
