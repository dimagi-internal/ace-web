import { describe, it, expect } from "vitest";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadProgramSpec } from "./spec.node";
import { parseDefaults, resolveBeats, filterDefaultsForSpec } from "./beats";
import { readFileSync } from "node:fs";

const here = path.dirname(fileURLToPath(import.meta.url));
// templates/ lives at the connect-videos package root, two dirs up from src/lib.
const repoRoot = path.resolve(here, "..", "..");
const exampleSpecPath = path.join(
  repoRoot,
  "templates",
  "connect-explainer",
  "example.spec.yaml",
);
const defaultsPath = path.join(repoRoot, "programs", "_defaults.yaml");

describe("connect-explainer example.spec.yaml", () => {
  it("validates against loadProgramSpec (explainer mode — no problem, no impact)", () => {
    const spec = loadProgramSpec(exampleSpecPath);
    expect(spec.slug).toBe("connect-explainer");
    expect(spec.name).toBe("CommCare Connect");
    expect(spec.problem).toBeUndefined();
    expect(spec.impact).toBeUndefined();
    expect(spec.product.beats).toHaveLength(4);
    expect(spec.product.beats.every((b) => b.is_demo_clip)).toBe(true);
    expect(spec.prospect).toBeUndefined();
  });

  it("filters the global timeline down to 6 beats (no stat-card beats)", () => {
    const spec = loadProgramSpec(exampleSpecPath);
    const defaults = parseDefaults(readFileSync(defaultsPath, "utf8"));
    const effective = filterDefaultsForSpec(defaults, spec);
    const timeline = resolveBeats(effective, spec.beat_overrides ?? {});
    const kinds = timeline.beats.map((b) => b.kind);
    expect(timeline.beats).toHaveLength(6);
    expect(kinds).not.toContain("body_problem_stat");
    expect(kinds).not.toContain("body_impact_stats");
    // The product walkthrough beat survives.
    expect(kinds).toContain("body_product_beats");
  });
});
