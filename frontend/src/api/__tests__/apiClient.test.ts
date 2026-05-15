import { describe, expect, it } from "vitest";
import { apiClient } from "../apiClient";
import type { components } from "../generated";

describe("apiClient typed client", () => {
  it("compiles with typed paths", () => {
    // Spot-check that codegen produced a schema we can reference. OppCardOut
    // was dropped from the OpenAPI schema when list_opps started returning a
    // free dict (the richer legacy card shape) — pick a stable schema instead.
    type WorkspaceOut = components["schemas"]["WorkspaceOut"];
    const sample: Partial<WorkspaceOut> = { slug: "x" };
    expect(sample.slug).toBe("x");
  });

  it("apiClient is created", () => {
    expect(apiClient).toBeDefined();
    expect(typeof apiClient.GET).toBe("function");
    expect(typeof apiClient.POST).toBe("function");
  });
});
