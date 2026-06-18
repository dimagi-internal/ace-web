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
  "program-designer",
  "example.spec.yaml",
);
const defaultsPath = path.join(repoRoot, "programs", "global_style.yaml");

describe("program-designer example.spec.yaml", () => {
  it("validates against loadProgramSpec (AI cut — ai_build + why benefit cards, no problem)", () => {
    const spec = loadProgramSpec(exampleSpecPath);
    expect(spec.slug).toBe("program-designer");
    expect(spec.name).toBe("Connect");
    expect(spec.active_cut).toBe("ai");
    expect(spec.ai_build).toBeDefined();
    expect(spec.ai_build?.components).toHaveLength(4);
    expect(spec.problem).toBeUndefined();
    // impact beat is repurposed as the three "why scale through Connect" cards.
    expect(spec.impact).toHaveLength(3);
    expect(spec.product?.beats).toHaveLength(4);
    expect(spec.product?.beats.every((b) => b.is_demo_clip)).toBe(true);
    // Generic, unbranded — partnership-pitch adds the prospect block.
    expect(spec.prospect).toBeUndefined();
    // Every rendered beat has a narration line (cta intentionally empty).
    expect(spec.narration.by_beat?.ai_build?.length).toBeGreaterThan(0);
    expect(spec.narration.by_beat?.impact?.length).toBeGreaterThan(0);
  });

  it("AI cut: 8 beats incl. body_ai_build, no problem stat, why beat kept (57s)", () => {
    const spec = loadProgramSpec(exampleSpecPath);
    const defaults = parseDefaults(readFileSync(defaultsPath, "utf8"));
    const timeline = resolveBeats(
      filterDefaultsForSpec(defaults, spec),
      spec.beat_overrides ?? {},
    );
    const kinds = timeline.beats.map((b) => b.kind);
    expect(timeline.beats).toHaveLength(8);
    expect(kinds).toContain("body_ai_build");
    expect(kinds).not.toContain("body_problem_stat");
    expect(kinds).toContain("body_impact_stats"); // the why beat
    expect(kinds).toContain("body_product_beats");
    expect(timeline.totalFrames).toBe(57 * timeline.fps);
  });

  it("standard cut: same spec with active_cut 'standard' drops ai_build (7 beats, 50s)", () => {
    const spec = loadProgramSpec(exampleSpecPath);
    const defaults = parseDefaults(readFileSync(defaultsPath, "utf8"));
    // Flip the one field — the non-AI cut is the same spec, one toggle.
    const standardSpec = { ...spec, active_cut: "standard" as const };
    const timeline = resolveBeats(
      filterDefaultsForSpec(defaults, standardSpec),
      spec.beat_overrides ?? {},
    );
    const kinds = timeline.beats.map((b) => b.kind);
    expect(timeline.beats).toHaveLength(7);
    expect(kinds).not.toContain("body_ai_build");
    // Everything else survives — including the why beat.
    expect(kinds).toContain("body_impact_stats");
    expect(kinds).toContain("body_product_beats");
    expect(timeline.totalFrames).toBe(50 * timeline.fps);
  });
});
