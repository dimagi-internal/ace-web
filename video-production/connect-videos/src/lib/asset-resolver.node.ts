/**
 * asset-resolver.node.ts — resolves `@alias` references in a ProgramSpec
 * to concrete asset paths under `public/assets/programs/<slug>/`.
 *
 * Lifecycle:
 *   1. Render pipeline parses program YAML (manifest + @aliases).
 *   2. Resolver walks every asset field, looks up @alias in spec.manifest.
 *   3. For `gdrive:<id>.<ext>` entries: checks the cache. If present,
 *      symlinks cache file into the program's public directory under
 *      the alias name. If absent, accumulates as missing.
 *   4. For `file:<path>` (or plain path) entries: leaves as-is.
 *   5. Returns rewritten spec (with concrete paths) plus a missing list.
 *
 * Cache layout: ~/.cache/connect-videos/<fileId>.<ext>
 *   (cross-worktree; survives clean-clones; populated by `npm run hydrate`)
 *
 * Public layout: <connect-videos>/public/assets/programs/<slug>/<alias>.<ext>
 *   (per-worktree; .gitignored; symlink to cache file)
 */

import path from "node:path";
import {
  existsSync,
  mkdirSync,
  linkSync,
  lstatSync,
  unlinkSync,
  statSync,
  copyFileSync,
} from "node:fs";
import os from "node:os";
import type { ProgramSpec } from "./spec";

export interface MissingAsset {
  alias: string;
  ref: string;
  gdriveId: string;
  ext: string;
  expectedCachePath: string;
}

export interface ResolveOptions {
  programSlug: string;
  publicRoot: string;        // absolute path to `public/`
  cacheDir?: string;         // override; defaults to ~/.cache/connect-videos
  // If true, only check presence; don't materialize symlinks. Useful for
  // hydrate which only cares about what's missing.
  checkOnly?: boolean;
}

export interface ResolveResult {
  spec: ProgramSpec;
  missing: MissingAsset[];
  cacheDir: string;
}

export function defaultCacheDir(): string {
  return path.join(os.homedir(), ".cache", "connect-videos");
}

interface ParsedRef {
  kind: "gdrive" | "file" | "plain";
  gdriveId?: string;
  ext?: string;
  path?: string;
}

function parseManifestRef(ref: string): ParsedRef {
  if (ref.startsWith("gdrive:")) {
    const body = ref.slice("gdrive:".length);
    const dot = body.lastIndexOf(".");
    if (dot <= 0) {
      throw new Error(
        `Manifest entry "${ref}" missing extension. Use gdrive:<fileId>.<ext>`
      );
    }
    return { kind: "gdrive", gdriveId: body.slice(0, dot), ext: body.slice(dot + 1) };
  }
  if (ref.startsWith("file:")) {
    return { kind: "file", path: ref.slice("file:".length) };
  }
  return { kind: "plain", path: ref };
}

interface ResolveCtx {
  manifest: Record<string, string>;
  cacheDir: string;
  programPublicDir: string;       // absolute path to public/assets/programs/<slug>
  programPublicRelative: string;  // path relative to public/ (used by staticFile())
  missing: MissingAsset[];
  checkOnly: boolean;
}

function rewriteAsset(value: string, ctx: ResolveCtx): string {
  if (!value.startsWith("@")) return value; // plain path, leave alone
  const alias = value.slice(1);
  const ref = ctx.manifest[alias];
  if (!ref) {
    throw new Error(
      `Asset reference "@${alias}" has no entry in spec.manifest. Add it under manifest: in the program YAML.`
    );
  }
  const parsed = parseManifestRef(ref);

  if (parsed.kind === "file") return parsed.path!;
  if (parsed.kind === "plain") return parsed.path!;

  // gdrive
  const cachePath = path.join(ctx.cacheDir, `${parsed.gdriveId}.${parsed.ext}`);
  const publicName = `${alias}.${parsed.ext}`;
  const publicAbs = path.join(ctx.programPublicDir, publicName);
  const publicRel = path.posix.join(ctx.programPublicRelative, publicName);

  if (!existsSync(cachePath)) {
    ctx.missing.push({
      alias,
      ref,
      gdriveId: parsed.gdriveId!,
      ext: parsed.ext!,
      expectedCachePath: cachePath,
    });
    // Still return the expected path; callers will surface missing[] and refuse to render.
    return publicRel;
  }

  if (!ctx.checkOnly) {
    mkdirSync(ctx.programPublicDir, { recursive: true });
    // Use a hard link (or replace existing one) instead of a symlink:
    // Remotion's bundler copies the public/ dir physically and doesn't
    // follow symlinks. Hard links share the underlying inode so the cache
    // and the public-side file always have identical bytes without
    // doubling disk usage.
    if (existsSync(publicAbs) || isStaleEntry(publicAbs, cachePath)) {
      unlinkSync(publicAbs);
    }
    if (!existsSync(publicAbs)) {
      try {
        linkSync(cachePath, publicAbs);
      } catch (err) {
        // Cross-device link not permitted (EXDEV) — happens when the
        // cache is on a bind-mounted host volume (Docker dev) and the
        // public/ dir is on the container filesystem. Fall back to a
        // file copy: Remotion's bundler reads the bytes either way, and
        // the duplication cost is bounded by the program's clip count.
        const e = err as NodeJS.ErrnoException;
        if (e?.code === "EXDEV") {
          copyFileSync(cachePath, publicAbs);
        } else {
          throw err;
        }
      }
    }
  }
  return publicRel;
}

function isStaleEntry(publicAbs: string, cachePath: string): boolean {
  // True if the public-side entry exists but doesn't point at the same
  // inode as the cache file (e.g. leftover symlink from an earlier run).
  try {
    const s1 = statSync(publicAbs);
    const s2 = statSync(cachePath);
    return s1.ino !== s2.ino;
  } catch {
    try {
      lstatSync(publicAbs);
      return true; // broken link
    } catch {
      return false;
    }
  }
}

/**
 * Walks every asset position in a ProgramSpec and rewrites `@alias` strings
 * into concrete paths (relative to public/, suitable for Remotion staticFile).
 * Returns a new spec object; the input is not mutated.
 */
export function resolveAssetRefs(spec: ProgramSpec, opts: ResolveOptions): ResolveResult {
  const cacheDir = opts.cacheDir ?? defaultCacheDir();
  mkdirSync(cacheDir, { recursive: true });

  const programPublicRelative = path.posix.join("assets", "programs", opts.programSlug);
  const programPublicDir = path.join(opts.publicRoot, programPublicRelative);

  const ctx: ResolveCtx = {
    manifest: spec.manifest ?? {},
    cacheDir,
    programPublicDir,
    programPublicRelative,
    missing: [],
    checkOnly: opts.checkOnly ?? false,
  };

  type SceneClip = NonNullable<ProgramSpec["scene"]>["clips"][number];
  const rewriteClipRef = (c: SceneClip): SceneClip => {
    if (typeof c === "string") return rewriteAsset(c, ctx);
    return { ...c, asset: rewriteAsset(c.asset, ctx) };
  };

  // scene/product/walkthrough are optional (walkthrough specs omit
  // scene+product; marketing/explainer specs omit walkthrough). Rewrite
  // each only when present so a missing block is left untouched.
  const rewritten: ProgramSpec = {
    ...spec,
    scene: spec.scene
      ? { ...spec.scene, clips: spec.scene.clips.map(rewriteClipRef) }
      : undefined,
    product: spec.product
      ? {
          ...spec.product,
          beats: spec.product.beats.map((b) => ({ ...b, asset: rewriteAsset(b.asset, ctx) })),
        }
      : undefined,
    walkthrough: spec.walkthrough
      ? Object.fromEntries(
          Object.entries(spec.walkthrough).map(([id, w]) => [
            id,
            { ...w, asset: rewriteAsset(w.asset, ctx) },
          ]),
        )
      : undefined,
  };

  return { spec: rewritten, missing: ctx.missing, cacheDir };
}

/**
 * Pretty-print the "you need to hydrate these" error block. Returns a
 * non-zero exit-style message string the caller can print + exit on.
 */
export function formatMissingError(missing: MissingAsset[], programSlug: string): string {
  const lines = [
    `Cannot render ${programSlug}: ${missing.length} asset(s) missing from cache.`,
    "",
    "Run:",
    `  npm run hydrate -- --program=${programSlug}`,
    "",
    "Missing entries (alias / Drive ID / expected cache path):",
    ...missing.map(
      (m) => `  @${m.alias}  ${m.gdriveId}  ${m.expectedCachePath}`
    ),
  ];
  return lines.join("\n");
}
