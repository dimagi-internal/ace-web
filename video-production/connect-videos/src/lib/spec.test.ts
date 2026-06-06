import { describe, it, expect } from "vitest";
import { loadProgramSpec, ProgramSpecError, resolveActiveByBeat } from "./spec.node";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = (name: string) => path.join(here, "__fixtures__", name);

describe("loadProgramSpec", () => {
  it("parses a valid spec into a typed object", () => {
    const spec = loadProgramSpec(fixture("valid.yaml"));
    expect(spec.slug).toBe("demo");
    expect(spec.problem.big).toBe("50%");
    expect(spec.product.beats).toHaveLength(1);
    expect(spec.impact).toHaveLength(2);
  });

  it("throws ProgramSpecError with field path on missing impact", () => {
    expect(() => loadProgramSpec(fixture("missing-impact.yaml")))
      .toThrowError(/impact/);
  });

  it("rejects a product.beats array with more than 4 entries (inline yaml)", () => {
    const badYaml = `
slug: demo
name: x
country_focus: x
status: x
tagline: x
program_url: https://x
scene: { clips: [a], lower_third: x }
problem: { big: "1", caption: x, source: x }
product:
  beats:
    - { asset: a, caption: b }
    - { asset: a, caption: b }
    - { asset: a, caption: b }
    - { asset: a, caption: b }
    - { asset: a, caption: b }
impact:
  - { big: "1", caption: x }
  - { big: "2", caption: y }
narration: { generator: manual, prompt_version: v1, script: x }
voice: { provider: elevenlabs, voice_id: a, model: eleven_turbo_v2 }
`;
    expect(() => loadProgramSpec(badYaml, { fromString: true }))
      .toThrowError(/product\.beats/);
  });
});

describe("narration variants", () => {
  const base = `
slug: noora-nigeria
name: Noora Health
country_focus: Nigeria
status: "[TBD] status"
tagline: t
program_url: https://example.org
scene: { clips: [a], lower_third: "Nigeria · Noora" }
problem: { big: "1", caption: c, source: s }
product:
  beats: [{ asset: a, caption: b }]
impact:
  - { big: "1", caption: x }
  - { big: "2", caption: y }
voice: { provider: elevenlabs, voice_id: v, model: eleven_turbo_v2 }
`;

  it("accepts a narration block with variants + active_angle", () => {
    const yaml = base + `
narration:
  generator: manual
  prompt_version: v3-partnership
  script: ""
  active_angle: the-scale-gap
  variants:
    - angle_id: day-in-the-life
      by_beat: { hook: "h1", cycle: "c1" }
    - angle_id: the-scale-gap
      by_beat: { hook: "h2", cycle: "c2" }
`;
    const spec = loadProgramSpec(yaml, { fromString: true });
    expect(spec.narration.variants).toHaveLength(2);
    expect(spec.narration.active_angle).toBe("the-scale-gap");
  });

  it("resolveActiveByBeat returns the active variant's by_beat", () => {
    const yaml = base + `
narration:
  generator: manual
  prompt_version: v3-partnership
  script: ""
  active_angle: the-scale-gap
  variants:
    - angle_id: day-in-the-life
      by_beat: { hook: "h1" }
    - angle_id: the-scale-gap
      by_beat: { hook: "h2" }
`;
    const spec = loadProgramSpec(yaml, { fromString: true });
    expect(resolveActiveByBeat(spec)).toEqual({ hook: "h2" });
  });

  it("resolveActiveByBeat falls back to legacy by_beat when no variants", () => {
    const yaml = base + `
narration:
  generator: manual
  prompt_version: v3
  script: ""
  by_beat: { hook: "legacy" }
`;
    const spec = loadProgramSpec(yaml, { fromString: true });
    expect(resolveActiveByBeat(spec)).toEqual({ hook: "legacy" });
  });

  it("rejects active_angle that names no variant", () => {
    const yaml = base + `
narration:
  generator: manual
  prompt_version: v3-partnership
  script: ""
  active_angle: nonexistent
  variants:
    - angle_id: day-in-the-life
      by_beat: { hook: "h1" }
`;
    expect(() => loadProgramSpec(yaml, { fromString: true }))
      .toThrowError(/active_angle/);
  });
});
