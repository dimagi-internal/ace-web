import { describe, it, expect } from "vitest";
import { loadProgramSpec, resolveActiveByBeat } from "./spec.node";
import { applyManifestRefs } from "./spec";
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

describe("applyManifestRefs", () => {
  // Build a parsed spec whose single scene clip references @c1, with the
  // manifest entry under test. The product beat uses a plain (non-@) asset
  // so only the clip exercises manifest resolution.
  const specWithManifestRef = (ref: string) =>
    loadProgramSpec(
      `
slug: demo
name: x
country_focus: x
status: x
tagline: x
program_url: https://x
manifest:
  c1: ${JSON.stringify(ref)}
scene: { clips: ["@c1"], lower_third: x }
product: { beats: [{ asset: plain.png, caption: b }] }
narration: { generator: manual, prompt_version: v1, script: x }
voice: { provider: elevenlabs, voice_id: a, model: eleven_turbo_v2 }
`,
      { fromString: true },
    );

  const clipAsset = (spec: ReturnType<typeof specWithManifestRef>): string =>
    (applyManifestRefs(spec).scene.clips[0] as unknown as { asset: string }).asset;

  it("rewrites a gdrive: ref to the program public asset path", () => {
    expect(clipAsset(specWithManifestRef("gdrive:ABC123.mp4"))).toBe(
      "assets/programs/demo/c1.mp4",
    );
  });

  it("strips the file: prefix to a plain local path", () => {
    expect(clipAsset(specWithManifestRef("file:/tmp/clip.mp4"))).toBe("/tmp/clip.mp4");
  });

  it("passes a plain path through unchanged (legacy form)", () => {
    expect(clipAsset(specWithManifestRef("some/local/clip.mp4"))).toBe(
      "some/local/clip.mp4",
    );
  });

  it("throws loud on an unresolved library: ref (must be staged to gdrive: first)", () => {
    // library: refs are rewritten server-side by render-prep staging
    // (apps/videos service._stage_spec) before the renderer runs. One
    // reaching applyManifestRefs means the spec was not staged — fail loud
    // rather than emit a broken literal asset path.
    expect(() =>
      clipAsset(specWithManifestRef("library:video/field-broll/walk.mp4")),
    ).toThrowError(/library:/);
    expect(() =>
      clipAsset(specWithManifestRef("library:video/field-broll/walk.mp4")),
    ).toThrowError(/staged|staging|_stage_spec/i);
  });

  it("throws when a @alias has no manifest entry", () => {
    const spec = loadProgramSpec(
      `
slug: demo
name: x
country_focus: x
status: x
tagline: x
program_url: https://x
scene: { clips: ["@missing"], lower_third: x }
product: { beats: [{ asset: plain.png, caption: b }] }
narration: { generator: manual, prompt_version: v1, script: x }
voice: { provider: elevenlabs, voice_id: a, model: eleven_turbo_v2 }
`,
      { fromString: true },
    );
    expect(() => applyManifestRefs(spec)).toThrowError(/has no entry in spec\.manifest/);
  });
});
