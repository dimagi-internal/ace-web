import { describe, it, expect } from "vitest";
import { loadProgramSpec, resolveActiveByBeat } from "./spec.node";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = (name: string) => path.join(here, "__fixtures__", name);

describe("loadProgramSpec", () => {
  it("parses a valid spec into a typed object", () => {
    const spec = loadProgramSpec(fixture("valid.yaml"));
    expect(spec.slug).toBe("demo");
    expect(spec.problem?.big).toBe("50%");
    expect(spec.product.beats).toHaveLength(1);
    expect(spec.impact).toHaveLength(2);
  });

  it("accepts a spec that omits impact (explainer mode — impact is optional)", () => {
    // Explainer-mode videos drop the impact stat-card beat entirely, so
    // a spec without `impact` is now valid. The body_impact_stats beat
    // is filtered out of the timeline upstream (filterDefaultsForSpec).
    const spec = loadProgramSpec(fixture("missing-impact.yaml"));
    expect(spec.impact).toBeUndefined();
    // Sibling fields still parse normally.
    expect(spec.problem?.big).toBe("50%");
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
    expect(spec.narration.variants![1].by_beat).toEqual({ hook: "h2", cycle: "c2" });
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

  it("rejects variants present without active_angle", () => {
    const yaml = base + `
narration:
  generator: manual
  prompt_version: v3-partnership
  script: ""
  variants:
    - angle_id: day-in-the-life
      by_beat: { hook: "h1" }
`;
    expect(() => loadProgramSpec(yaml, { fromString: true }))
      .toThrowError(/active_angle/);
  });
});

describe("partnership-valid fixture", () => {
  it("loads the partnership-valid fixture with 3 variants + a demo clip", () => {
    const spec = loadProgramSpec(fixture("partnership-valid.yaml"));
    expect(spec.narration.variants).toHaveLength(3);
    expect(spec.narration.active_angle).toBe("the-scale-gap");
    expect(spec.prospect?.name).toBeTruthy();
    expect(spec.product.beats.some((b) => b.is_demo_clip)).toBe(true);
  });
});

describe("prospect + is_demo_clip", () => {
  const base = `
slug: noora-nigeria
name: Noora Health
country_focus: Nigeria
status: s
tagline: t
program_url: https://example.org
scene: { clips: [a], lower_third: "x" }
problem: { big: "1", caption: c, source: s }
impact:
  - { big: "1", caption: x }
  - { big: "2", caption: y }
narration: { generator: manual, prompt_version: v3, script: x, by_beat: { hook: h } }
voice: { provider: elevenlabs, voice_id: v, model: eleven_turbo_v2 }
`;

  it("accepts a prospect block", () => {
    const spec = loadProgramSpec(base + `
prospect: { name: "Noora Health", logo_asset: "@prospect_logo", region: "Nigeria", sector: "MNCH" }
product: { beats: [{ asset: a, caption: b }] }
`, { fromString: true });
    expect(spec.prospect?.name).toBe("Noora Health");
  });

  it("treats prospect as optional (legacy specs)", () => {
    const spec = loadProgramSpec(base + `
product: { beats: [{ asset: a, caption: b }] }
`, { fromString: true });
    expect(spec.prospect).toBeUndefined();
  });

  it("accepts is_demo_clip on a product beat and defaults it false", () => {
    const spec = loadProgramSpec(base + `
product:
  beats:
    - { asset: clip.mp4, caption: "real demo", is_demo_clip: true }
    - { asset: shot.png, caption: "screenshot" }
`, { fromString: true });
    expect(spec.product.beats[0].is_demo_clip).toBe(true);
    expect(spec.product.beats[1].is_demo_clip).toBe(false);
  });
});
