import { describe, expect, it } from "vitest";
import { apiV2 } from "../client.v2";
import type { components } from "../generated";

describe("apiV2 typed client", () => {
  it("compiles with typed paths", () => {
    // Spot-check that codegen produced a schema we can reference. OppCardOut
    // was dropped from the OpenAPI schema when list_opps started returning a
    // free dict (the richer legacy card shape) — pick a stable schema instead.
    type WorkspaceOut = components["schemas"]["WorkspaceOut"];
    const sample: Partial<WorkspaceOut> = { slug: "x" };
    expect(sample.slug).toBe("x");
  });

  it("apiV2 client is created", () => {
    expect(apiV2).toBeDefined();
    expect(typeof apiV2.GET).toBe("function");
    expect(typeof apiV2.POST).toBe("function");
  });
});
