// Generate TypeScript types from canopy's canonical narrative JSON Schema.
//
// Source of truth: canopy `scripts/narrative/schema/json/*.json` (pydantic
// dumps), vendored into `src/api/narrative-schema/`. This kills the drift
// between canopy's substrate and ACE's hand-written types — the narrative /
// scene / evidence / review-package shapes are GENERATED, never edited.
//
// Refresh the vendored schemas from a canopy checkout, then regenerate:
//   npm run gen:narrative
//
// NOTE: this is the canopy *narrative* contract (UnifiedSpec, Scene, Feature,
// WhyBrief, Evidence, Gap, ReviewRequest, Verdict-for-DDD). It is NOT ACE's
// `-eval` verdict (`lib/verdict-schema.ts` in the ace plugin) — that is a
// separate, ACE-specific artifact and stays hand-written.
import { compileFromFile } from "json-schema-to-typescript";
import { readdirSync, writeFileSync, mkdirSync } from "node:fs";
import { join, basename } from "node:path";

const SCHEMA_DIR = "src/api/narrative-schema";
const OUT_DIR = "src/api/narrative-contract";

mkdirSync(OUT_DIR, { recursive: true });
const files = readdirSync(SCHEMA_DIR)
  .filter((f) => f.endsWith(".json"))
  .sort();

const roots = [];
for (const f of files) {
  const name = basename(f, ".json");
  const ts = await compileFromFile(join(SCHEMA_DIR, f), {
    bannerComment: `// GENERATED from canopy scripts/narrative/schema/json/${f} — do not edit. Run \`npm run gen:narrative\`.`,
    style: { singleQuote: false },
  });
  writeFileSync(join(OUT_DIR, `${name}.ts`), ts);
  roots.push(name);
}

const barrel =
  `// GENERATED barrel for the canopy narrative contract — do not edit. Run \`npm run gen:narrative\`.\n` +
  roots.map((n) => `export type { ${n} } from "./${n}";`).join("\n") +
  "\n";
writeFileSync(join(OUT_DIR, "index.ts"), barrel);
console.log("generated narrative contract:", roots.join(", "));
