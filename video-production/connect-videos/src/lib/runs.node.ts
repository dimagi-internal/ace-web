/**
 * Per-program runs layout helpers.
 *
 *   programs/<slug>/runs/run-001/spec.yaml      ← video spec (was: programs/<slug>.yaml)
 *   programs/<slug>/runs/run-001/output.mp4     ← muxed render (was: out/<slug>-draft-mux.mp4)
 *   programs/<slug>/runs/run-001/explorer/      ← built explorer (was: out/clip-explorer/<slug>/)
 *
 * Mirrors the opps/runs model in ace-web — each iteration is a folder
 * snapshot, so you can fork a run, edit, re-render, and diff side-by-side.
 *
 * Run IDs are strings like ``run-001``, ``run-002``, etc. Helpers below
 * pick the highest-numbered run as "latest" by default.
 */
import { existsSync, mkdirSync, readdirSync, copyFileSync, cpSync } from "node:fs";
import path from "node:path";

export interface RunRef {
  slug: string;
  runId: string;
  root: string; // connect-videos project root
}

export function programDir(slug: string, root: string): string {
  return path.join(root, "programs", slug);
}

export function runsDir(slug: string, root: string): string {
  return path.join(programDir(slug, root), "runs");
}

export function runDir(slug: string, runId: string, root: string): string {
  return path.join(runsDir(slug, root), runId);
}

export function specPath(slug: string, runId: string, root: string): string {
  return path.join(runDir(slug, runId, root), "spec.yaml");
}

export function outputPath(slug: string, runId: string, root: string): string {
  return path.join(runDir(slug, runId, root), "output.mp4");
}

export function explorerDir(slug: string, runId: string, root: string): string {
  return path.join(runDir(slug, runId, root), "explorer");
}

const RUN_RE = /^run-(\d{3,})$/;

export function listRunIds(slug: string, root: string): string[] {
  const dir = runsDir(slug, root);
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory() && RUN_RE.test(e.name))
    .map((e) => e.name)
    .sort();
}

export function latestRunId(slug: string, root: string): string {
  const ids = listRunIds(slug, root);
  if (ids.length === 0) {
    throw new Error(
      `No runs found for program ${JSON.stringify(slug)} at ${runsDir(slug, root)}. Expected programs/${slug}/runs/run-NNN/spec.yaml.`
    );
  }
  return ids[ids.length - 1];
}

export function nextRunId(slug: string, root: string): string {
  const ids = listRunIds(slug, root);
  if (ids.length === 0) return "run-001";
  const last = ids[ids.length - 1];
  const n = parseInt(last.replace("run-", ""), 10);
  return "run-" + String(n + 1).padStart(3, "0");
}

/**
 * Resolve the requested run, defaulting to the latest. Useful for CLI
 * flags like ``--run=<id>`` where an empty/undefined value means
 * "operate on the most recent run".
 */
export function resolveRun(slug: string, runId: string | undefined | null, root: string): string {
  return runId && runId.trim() ? runId.trim() : latestRunId(slug, root);
}

/**
 * Fork a run: copy spec.yaml from ``fromRunId`` into a brand-new
 * ``run-NNN`` directory and return the new run id. The new run starts
 * empty otherwise — no output.mp4, no explorer/. Re-render to fill them
 * in. Mirrors ``ace`` opp run-fork semantics: the spec is the only
 * required carry-over; everything else is rebuilt.
 */
export function forkRun(slug: string, fromRunId: string, root: string): string {
  const src = specPath(slug, fromRunId, root);
  if (!existsSync(src)) {
    throw new Error(`Source run not found: ${src}`);
  }
  const next = nextRunId(slug, root);
  const dst = runDir(slug, next, root);
  mkdirSync(dst, { recursive: true });
  copyFileSync(src, path.join(dst, "spec.yaml"));
  return next;
}

/** Convenience — every dir directly under ``programs/`` that has a runs/ subdir is a program. */
export function listPrograms(root: string): string[] {
  const dir = path.join(root, "programs");
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory() && existsSync(runsDir(e.name, root)))
    .map((e) => e.name)
    .sort();
}

// cpSync is re-exported so tests can `import { cpSync } from "./runs.node"`
// without pulling in the rest of node:fs.
export { cpSync };
