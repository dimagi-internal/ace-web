import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join, dirname, basename } from "node:path";
import { fileURLToPath } from "node:url";
import type { Verdict, ReviewRequest, UnifiedSpec } from "../narrative-contract";

const here = dirname(fileURLToPath(import.meta.url));
const SCHEMA_DIR = join(here, "..", "narrative-schema");
const CONTRACT_DIR = join(here, "..", "narrative-contract");

describe("narrative contract (generated from canopy JSON Schema)", () => {
  const schemas = readdirSync(SCHEMA_DIR)
    .filter((f) => f.endsWith(".json"))
    .map((f) => basename(f, ".json"));

  it("vendors the expected canopy schemas", () => {
    expect(schemas.sort()).toEqual([
      "Decision",
      "Feature",
      "ReviewRequest",
      "RunState",
      "UnifiedSpec",
      "Verdict",
      "WhyBrief",
    ]);
  });

  it("generates a TS module exporting each schema's root interface", () => {
    for (const name of schemas) {
      const file = join(CONTRACT_DIR, `${name}.ts`);
      expect(existsSync(file), `${name}.ts missing — run npm run gen:narrative`).toBe(true);
      const src = readFileSync(file, "utf8");
      expect(src).toContain(`export interface ${name} {`);
      expect(src).toContain("GENERATED from canopy");
    }
  });

  it("re-exports every root from the barrel", () => {
    const barrel = readFileSync(join(CONTRACT_DIR, "index.ts"), "utf8");
    for (const name of schemas) {
      expect(barrel).toContain(`export type { ${name} } from "./${name}";`);
    }
  });

  it("types are usable (compile-time conformance)", () => {
    // If these assignments stop compiling, the canopy contract shape changed —
    // regenerate and update consumers.
    const v: Verdict = { dimensions: {}, overall_score: 4.2, verdict: "pass" };
    expect(v.verdict).toBe("pass");
    // ReviewRequest + UnifiedSpec are the Stage 5 review-package + structured
    // narrative shapes; reference them so tsc keeps them honest.
    const touch = (_r?: ReviewRequest, _s?: UnifiedSpec) => undefined;
    touch();
    expect(typeof touch).toBe("function");
  });
});
