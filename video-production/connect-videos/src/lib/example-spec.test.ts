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
const defaultsPath = path.join(repoRoot, "programs", "global_style.yaml");

describe("connect-explainer example.spec.yaml", () => {
  it("validates against loadProgramSpec (explainer mode — no problem, no impact)", () => {
    const spec = loadProgramSpec(exampleSpecPath);
    expect(spec.slug).toBe("connect-explainer");
    expect(spec.name).toBe("Connect");
    expect(spec.problem).toBeUndefined();
    expect(spec.impact).toBeUndefined();
    expect(spec.product?.beats).toHaveLength(4);
    expect(spec.product?.beats.every((b) => b.is_demo_clip)).toBe(true);
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

  it("filtered timeline is 42s (1260 frames) — the duration the renderer must use", () => {
    // Regression guard: the explainer render must size the composition to
    // the FILTERED timeline. The unfiltered global defaults are 67s (2010
    // frames) since the program-designer change added the 7s ai_build
    // beat; dropping ai_build (7s, no ai_build block) + problem (10s) +
    // impact (8s) leaves 42s. render.ts and the Composition.calculateMetadata
    // both apply filterDefaultsForSpec — if either reverts to the unfiltered
    // defaults the explainer render grows a black tail (and post-scene
    // captions drift later).
    const spec = loadProgramSpec(exampleSpecPath);
    const defaults = parseDefaults(readFileSync(defaultsPath, "utf8"));
    const unfiltered = resolveBeats(defaults, spec.beat_overrides ?? {});
    const filtered = resolveBeats(
      filterDefaultsForSpec(defaults, spec),
      spec.beat_overrides ?? {},
    );
    expect(unfiltered.totalFrames).toBe(67 * unfiltered.fps);
    expect(filtered.totalFrames).toBe(42 * filtered.fps);
    expect(filtered.totalFrames).toBeLessThan(unfiltered.totalFrames);
  });
});
