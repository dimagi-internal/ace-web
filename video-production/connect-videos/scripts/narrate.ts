#!/usr/bin/env tsx
import { readFileSync, writeFileSync } from "node:fs";
import { parse, stringify } from "yaml";
import path from "node:path";
import { generateNarration } from "../src/lib/narration";
import { loadProgramSpec } from "../src/lib/spec.node";
import { resolveRun, specPath } from "../src/lib/runs.node";

function parseArgs(): { program: string; run: string; durationSeconds: number; dryRun: boolean } {
  const args = process.argv.slice(2);
  const program = args.find((a) => a.startsWith("--program="))?.split("=")[1];
  const run = args.find((a) => a.startsWith("--run="))?.split("=")[1] ?? "";
  const duration = args.find((a) => a.startsWith("--duration="))?.split("=")[1];
  const dryRun = args.includes("--dry-run");
  if (!program) {
    console.error("Usage: npm run narrate -- --program=<slug> [--run=<run-NNN>] [--duration=37] [--dry-run]");
    process.exit(2);
  }
  return {
    program,
    run,
    durationSeconds: duration ? Number(duration) : 37,
    dryRun,
  };
}

async function main() {
  const { program, run, durationSeconds, dryRun } = parseArgs();
  const runId = resolveRun(program, run, process.cwd());
  const yamlPath = specPath(program, runId, process.cwd());
  const spec = loadProgramSpec(yamlPath);
  if (spec.narration.generator !== "anthropic") {
    console.error(
      `narration.generator is "${spec.narration.generator}" — refusing to overwrite. Set it to "anthropic" in ${yamlPath} first.`
    );
    process.exit(1);
  }
  console.log(`Drafting narration for ${spec.name} (${durationSeconds}s body)…`);
  const script = await generateNarration(spec, {
    wordsPerMinute: 150,
    durationSeconds,
  });
  console.log("\n--- generated narration ---\n");
  console.log(script);
  console.log("\n---------------------------\n");
  if (dryRun) return;
  const raw = readFileSync(yamlPath, "utf8");
  const obj = parse(raw);
  obj.narration.script = script;
  writeFileSync(yamlPath, stringify(obj, { lineWidth: 0 }));
  console.log(`Wrote narration.script back to ${yamlPath}.`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
