#!/usr/bin/env tsx
/**
 * hydrate.ts — make all manifest-referenced assets present in the local
 * cache so a program can be rendered.
 *
 * Modes:
 *
 *   1. Status (default):
 *        npm run hydrate -- --program=chc
 *      Lists missing/present cached entries. Exits 0 if all present, 1 if any
 *      missing. Output gives Drive IDs the assistant should pull next.
 *
 *   2. Decode-and-seed:
 *        npm run hydrate -- --program=chc --decode=<tool-result.txt>[,<...>]
 *      Decodes one or more `drive_download_binary` tool-result JSON dumps and
 *      writes them into the cache under `<fileId>.<ext>`. Use this after the
 *      assistant has fetched a binary via MCP — the JSON lands at a known path
 *      and this command turns it into a cached video/audio/image file.
 *
 *   3. Adopt:
 *        npm run hydrate -- --program=chc --adopt=<dir>
 *      For each manifest entry whose gdrive fileId matches a file in <dir>
 *      (named `<fileId>.<ext>` OR matching by mimeType+size), copies it into
 *      the cache. Useful for one-time migrations from existing
 *      `public/assets/programs/<slug>/` directories or Drive Desktop syncs.
 *
 * After running with any seed-mode, the script always re-checks status.
 */

import path from "node:path";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  writeFileSync,
} from "node:fs";
import { loadProgramSpec } from "../src/lib/spec.node";
import { resolveRun, specPath } from "../src/lib/runs.node";
import {
  resolveAssetRefs,
  defaultCacheDir,
  type MissingAsset,
} from "../src/lib/asset-resolver.node";

interface CliArgs {
  program: string;
  decodePaths: string[];
  adoptDir: string | null;
}

function parseArgs(): CliArgs {
  const args = process.argv.slice(2);
  const program = args.find((a) => a.startsWith("--program="))?.slice("--program=".length);
  const decodeRaw = args.find((a) => a.startsWith("--decode="))?.slice("--decode=".length);
  const adoptDir = args.find((a) => a.startsWith("--adopt="))?.slice("--adopt=".length) ?? null;
  if (!program) {
    console.error(
      "Usage:\n  npm run hydrate -- --program=<slug>\n  npm run hydrate -- --program=<slug> --decode=<tool-result.txt>[,<...>]\n  npm run hydrate -- --program=<slug> --adopt=<dir>"
    );
    process.exit(2);
  }
  return {
    program,
    decodePaths: decodeRaw ? decodeRaw.split(",").map((s) => s.trim()).filter(Boolean) : [],
    adoptDir,
  };
}

interface DriveResult {
  id: string;
  name: string;
  mimeType: string;
  size: number;
  content_base64: string;
}

function decodeIntoCache(toolResultPath: string, cacheDir: string): { id: string; ext: string; path: string } {
  const result: DriveResult = JSON.parse(readFileSync(toolResultPath, "utf8"));
  // Choose the extension from the mime type. Falls back to whatever the
  // filename suggests so audio/wav and the like stay correct.
  const mimeExt: Record<string, string> = {
    "video/mp4": "mp4",
    "audio/wav": "wav",
    "audio/mpeg": "mp3",
    "image/jpeg": "jpg",
    "image/png": "png",
  };
  let ext = mimeExt[result.mimeType];
  if (!ext) {
    const m = result.name.match(/\.([a-zA-Z0-9]{2,4})$/);
    ext = m ? m[1].toLowerCase() : "bin";
  }
  const outPath = path.join(cacheDir, `${result.id}.${ext}`);
  mkdirSync(cacheDir, { recursive: true });
  writeFileSync(outPath, Buffer.from(result.content_base64, "base64"));
  return { id: result.id, ext, path: outPath };
}

function adoptFromDir(missing: MissingAsset[], adoptDir: string, cacheDir: string): number {
  let adopted = 0;
  for (const m of missing) {
    // Prefer exact fileId match in adoptDir (renamed file).
    const expectedName = `${m.gdriveId}.${m.ext}`;
    const direct = path.join(adoptDir, expectedName);
    if (existsSync(direct)) {
      copyFileSync(direct, m.expectedCachePath);
      adopted++;
      console.log(`adopted ${expectedName} -> ${m.expectedCachePath}`);
      continue;
    }
    // Fallback: find any file with matching extension in adoptDir, ask user
    // to rename. (We can't safely guess content matches at this scale.)
  }
  return adopted;
}

function reportStatus(programSlug: string, publicRoot: string, cacheDir: string): MissingAsset[] {
  const runId = resolveRun(programSlug, "", process.cwd());
  const yamlPath = specPath(programSlug, runId, process.cwd());
  const spec = loadProgramSpec(yamlPath);
  const { missing } = resolveAssetRefs(spec, {
    programSlug,
    publicRoot,
    cacheDir,
    checkOnly: false, // materialize while we're at it
  });

  const aliases = Object.keys(spec.manifest ?? {});
  console.log(
    `Program "${programSlug}" — manifest entries: ${aliases.length}, missing: ${missing.length}`
  );
  if (missing.length === 0) {
    console.log("All assets present in cache and materialized to public/.");
    return missing;
  }
  console.log("\nMissing entries (alias  gdriveId  ext  expected-cache-path):");
  for (const m of missing) {
    console.log(`  @${m.alias}\t${m.gdriveId}\t${m.ext}\t${m.expectedCachePath}`);
  }
  console.log(
    "\nTo seed:\n  1. Pull each Drive ID via the ace-gdrive MCP (drive_download_binary).\n  2. Run:  npm run hydrate -- --program=" +
      programSlug +
      " --decode=<tool-result.txt>[,<...>]\n  3. Or:   drop fileId-named files into <dir> and run with --adopt=<dir>"
  );
  return missing;
}

function main() {
  const cli = parseArgs();
  const cacheDir = defaultCacheDir();
  const publicRoot = path.resolve("public");
  mkdirSync(cacheDir, { recursive: true });

  // Seeders (run before status so the post-run report reflects results)
  for (const p of cli.decodePaths) {
    const r = decodeIntoCache(p, cacheDir);
    console.log(`decoded ${path.basename(p)} -> ${r.path} (id=${r.id}, ext=${r.ext})`);
  }
  if (cli.adoptDir) {
    // Need the missing list first to know what to adopt.
    const runId = resolveRun(cli.program, "", process.cwd());
    const yamlPath = specPath(cli.program, runId, process.cwd());
    const spec = loadProgramSpec(yamlPath);
    const { missing } = resolveAssetRefs(spec, {
      programSlug: cli.program,
      publicRoot,
      cacheDir,
      checkOnly: true,
    });
    const n = adoptFromDir(missing, cli.adoptDir, cacheDir);
    console.log(`adopted ${n} file(s) from ${cli.adoptDir}`);
  }

  const missingAfter = reportStatus(cli.program, publicRoot, cacheDir);
  process.exit(missingAfter.length === 0 ? 0 : 1);
}

main();
