#!/usr/bin/env tsx
/**
 * build-clip-explorer.ts — generate a slick local web page that
 * visualizes a program's clip assignments:
 *
 *   - Plays the final rendered video at the top.
 *   - For each beat, shows the assigned source clips with a player +
 *     a "used range" overlay on the timeline, so you can scrub the
 *     full clip and decide whether the slice we picked is the best
 *     window (or whether we should swap in a different clip).
 *   - Calls out beats with no assigned clip and manifest entries we
 *     have but aren't currently using.
 *
 * Output:
 *   out/clip-explorer/<slug>/
 *     index.html  -- self-contained page (inline CSS+JS)
 *     media/      -- symlinks to source MP4s + final render
 *
 * Run via `npm run explore -- --program=chc` (also starts a server).
 */

import path from "node:path";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { execSync } from "node:child_process";
import { loadProgramSpec } from "../src/lib/spec.node";
import { loadDefaults, resolveBeats, type ResolvedBeat } from "../src/lib/beats.node";
import { defaultCacheDir } from "../src/lib/asset-resolver.node";

interface CliArgs {
  program: string;
  open: boolean;
}

function parseArgs(): CliArgs {
  const args = process.argv.slice(2);
  const program = args.find((a) => a.startsWith("--program="))?.slice("--program=".length);
  if (!program) {
    console.error("Usage: npm run build-clip-explorer -- --program=<slug>");
    process.exit(2);
  }
  return { program, open: args.includes("--open") };
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
    return { kind: "gdrive", gdriveId: body.slice(0, dot), ext: body.slice(dot + 1) };
  }
  if (ref.startsWith("file:")) return { kind: "file", path: ref.slice("file:".length) };
  return { kind: "plain", path: ref };
}

function aliasFromRef(value: string): string | null {
  return value.startsWith("@") ? value.slice(1) : null;
}

function fmtTs(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = (sec % 60).toFixed(1);
  return `${m}:${s.padStart(4, "0")}`;
}

function probe(file: string): { duration: number; width: number; height: number } {
  const out = execSync(
    `ffprobe -v error -of csv=p=0 -select_streams v:0 -show_entries stream=width,height:format=duration ${JSON.stringify(file)}`
  ).toString().trim();
  // Output is two lines: "WxH" then "duration"
  const lines = out.split("\n").map((l) => l.trim()).filter(Boolean);
  let w = 0, h = 0, dur = 0;
  for (const line of lines) {
    if (line.includes(",")) {
      const [a, b] = line.split(",");
      w = Number(a); h = Number(b);
    } else if (/^\d/.test(line)) {
      dur = Number(line);
    }
  }
  return { duration: dur, width: w, height: h };
}

interface BeatBlock {
  id: string;
  kind: string;
  startSec: number;
  endSec: number;
  durationSec: number;
  narration: string;
  assignments: ClipAssignment[];
  // If this beat takes asset slots but they're empty/missing, flagged.
  missingSlots: string[];
}

// Plain-language labels keyed by beat id. The schema-level term is "beat"
// (screenwriting jargon for a narrative unit) but the UI uses "section".
const SECTION_LABELS: Record<string, { name: string; subtitle: string }> = {
  hook:    { name: "Opening tagline",       subtitle: "The headline that frames the whole video — Connect's value prop." },
  cycle:   { name: "How Connect works",     subtitle: "The four-step cycle: Learn → Deliver → Verify → Pay." },
  handoff: { name: "Program handoff",       subtitle: "Names which program we're about to dive into." },
  scene:   { name: "Field footage",         subtitle: "Real footage from the program location — sets the scene." },
  problem: { name: "Headline stat",         subtitle: "One big number that frames the problem or scale." },
  product: { name: "Connect app walkthrough", subtitle: "Short phone-frame clips of the Connect platform in use." },
  impact:  { name: "Results numbers",       subtitle: "Two big numbers — what the program has delivered." },
  cta:     { name: "End card",              subtitle: "Logo + tagline + 'become a delivery partner' CTA." },
};

function sectionLabel(beatId: string): { name: string; subtitle: string } {
  return SECTION_LABELS[beatId] ?? { name: beatId, subtitle: "" };
}

interface ClipAssignment {
  role: string;             // "scene-clip[0]", "product-beat[1].asset", etc.
  alias: string | null;     // null if a literal path
  refRaw: string;           // original ref string
  sourcePath: string | null;
  sourceDuration: number | null;
  sourceRes: string | null;
  usedStartSec: number;
  usedDurationSec: number;
  gdriveId: string | null;
  status: "ok" | "missing-cache" | "alias-unknown" | "literal-path";
  // Identifies which YAML path the explorer's /edit endpoint should
  // update when a slider is dragged. Set when we wire scene-clip /
  // product-beat assignments.
  editScope?: { path: string; kind: "scene-clip" | "product-beat"; index: number };
}

function main() {
  const cli = parseArgs();
  const root = process.cwd();
  const defaults = loadDefaults(path.join(root, "programs/_defaults.yaml"));
  const spec = loadProgramSpec(path.join(root, `programs/${cli.program}.yaml`));
  const timeline = resolveBeats(defaults, spec.beat_overrides ?? {});
  const cacheDir = defaultCacheDir();

  const outDir = path.join(root, "out", "clip-explorer", cli.program);
  if (existsSync(outDir)) rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  const mediaDir = path.join(outDir, "media");
  mkdirSync(mediaDir, { recursive: true });

  // Mirror the final render
  const finalSrc = path.join(root, `out/${cli.program}-draft-mux.mp4`);
  const finalLink = path.join(mediaDir, "final.mp4");
  if (existsSync(finalSrc)) symlinkSync(finalSrc, finalLink);

  // Resolve all assignments (scene + product). Walk the spec.
  const beatBlocks: BeatBlock[] = [];

  const beatById = Object.fromEntries(
    timeline.beats.map((b) => [b.id, b])
  ) as Record<string, ResolvedBeat>;

  function resolveAlias(refRaw: string, role: string, slotDurationSec: number): ClipAssignment {
    const alias = aliasFromRef(refRaw);
    if (!alias) {
      return {
        role,
        alias: null,
        refRaw,
        sourcePath: null,
        sourceDuration: null,
        sourceRes: null,
        usedStartSec: 0,
        usedDurationSec: slotDurationSec,
        gdriveId: null,
        status: "literal-path",
      };
    }
    const entry = spec.manifest?.[alias];
    if (!entry) {
      return {
        role,
        alias,
        refRaw,
        sourcePath: null,
        sourceDuration: null,
        sourceRes: null,
        usedStartSec: 0,
        usedDurationSec: slotDurationSec,
        gdriveId: null,
        status: "alias-unknown",
      };
    }
    const parsed = parseManifestRef(entry);
    if (parsed.kind === "gdrive") {
      const cachePath = path.join(cacheDir, `${parsed.gdriveId}.${parsed.ext}`);
      const present = existsSync(cachePath);
      if (!present) {
        return {
          role,
          alias,
          refRaw,
          sourcePath: null,
          sourceDuration: null,
          sourceRes: null,
          usedStartSec: 0,
          usedDurationSec: slotDurationSec,
          gdriveId: parsed.gdriveId!,
          status: "missing-cache",
        };
      }
      // Symlink into media/ for the page
      const mediaName = `${alias}.${parsed.ext}`;
      const mediaLink = path.join(mediaDir, mediaName);
      if (!existsSync(mediaLink)) symlinkSync(cachePath, mediaLink);
      const probed = probe(cachePath);
      return {
        role,
        alias,
        refRaw,
        sourcePath: `media/${mediaName}`,
        sourceDuration: probed.duration,
        sourceRes: `${probed.width}x${probed.height}`,
        usedStartSec: 0,
        usedDurationSec: Math.min(slotDurationSec, probed.duration),
        gdriveId: parsed.gdriveId!,
        status: "ok",
      };
    }
    return {
      role,
      alias,
      refRaw,
      sourcePath: parsed.path ?? null,
      sourceDuration: null,
      sourceRes: null,
      usedStartSec: 0,
      usedDurationSec: slotDurationSec,
      gdriveId: null,
      status: "literal-path",
    };
  }

  // Build per-beat blocks
  for (const b of timeline.beats) {
    const startSec = b.startFrame / timeline.fps;
    const endSec = (b.startFrame + b.durationFrames) / timeline.fps;
    const block: BeatBlock = {
      id: b.id,
      kind: b.kind,
      startSec,
      endSec,
      durationSec: b.durationFrames / timeline.fps,
      narration: spec.narration.by_beat?.[b.id] ?? "",
      assignments: [],
      missingSlots: [],
    };

    if (b.kind === "body_scene") {
      const slotPer = block.durationSec / spec.scene.clips.length;
      spec.scene.clips.forEach((c, i) => {
        // Clip can be a bare alias string or an object with start_seconds.
        const refRaw = typeof c === "string" ? c : c.asset;
        const startSec = typeof c === "string" ? 0 : (c.start_seconds ?? 0);
        const a = resolveAlias(refRaw, `scene-clip[${i}]`, slotPer);
        a.usedStartSec = startSec;
        a.usedDurationSec = Math.min(slotPer, (a.sourceDuration ?? Infinity) - startSec);
        a.editScope = { path: `scene.clips[${i}]`, kind: "scene-clip", index: i };
        block.assignments.push(a);
      });
    } else if (b.kind === "body_product_beats") {
      const slotPer = block.durationSec / spec.product.beats.length;
      spec.product.beats.forEach((pb, i) => {
        const a = resolveAlias(pb.asset, `product-beat[${i}].asset`, slotPer);
        a.usedStartSec = pb.start_seconds ?? 0;
        a.usedDurationSec = Math.min(slotPer, (a.sourceDuration ?? Infinity) - a.usedStartSec);
        a.editScope = { path: `product.beats[${i}]`, kind: "product-beat", index: i };
        block.assignments.push(a);
      });
    } else if (b.kind === "body_problem_stat") {
      // problem renders a stat card; doesn't take a clip slot
      block.missingSlots.push("no-visual-asset (uses problem stat data)");
    } else if (b.kind === "body_impact_stats") {
      block.missingSlots.push("no-visual-asset (uses impact stat data)");
    }
    beatBlocks.push(block);
  }

  // Identify manifest entries that are present but unused
  const usedAliases = new Set<string>();
  for (const blk of beatBlocks)
    for (const a of blk.assignments) if (a.alias) usedAliases.add(a.alias);

  const allAliases = Object.keys(spec.manifest ?? {});
  const unusedAliases = allAliases.filter((a) => !usedAliases.has(a));

  // For unused entries, also probe + link so the page can preview them
  const unusedClips: UnusedClip[] = unusedAliases.map((alias) => {
    const entry = spec.manifest![alias];
    const parsed = parseManifestRef(entry);
    if (parsed.kind !== "gdrive") return { alias, status: "non-gdrive", entry };
    const cachePath = path.join(cacheDir, `${parsed.gdriveId}.${parsed.ext}`);
    if (!existsSync(cachePath)) {
      return { alias, status: "missing-cache", entry, gdriveId: parsed.gdriveId };
    }
    const mediaName = `${alias}.${parsed.ext}`;
    const mediaLink = path.join(mediaDir, mediaName);
    if (!existsSync(mediaLink)) symlinkSync(cachePath, mediaLink);
    const probed = probe(cachePath);
    return {
      alias,
      status: "ok",
      entry,
      gdriveId: parsed.gdriveId,
      sourcePath: `media/${mediaName}`,
      sourceDuration: probed.duration,
      sourceRes: `${probed.width}x${probed.height}`,
    };
  });

  // Compute coverage metrics for the header.
  const totalAssignments = beatBlocks.flatMap((b) => b.assignments).length;
  const okAssignments = beatBlocks
    .flatMap((b) => b.assignments)
    .filter((a) => a.status === "ok").length;

  // Render HTML
  const html = renderHtml({
    program: cli.program,
    spec,
    timeline,
    beatBlocks,
    unusedClips,
    totalAssignments,
    okAssignments,
    finalAvailable: existsSync(finalLink),
  });
  writeFileSync(path.join(outDir, "index.html"), html);

  // --- Library tab: every manifest entry, with usage badges ---
  const allEntries = Object.entries(spec.manifest ?? {}).map(([alias, entry]) => {
    const parsed = parseManifestRef(entry);
    let cached = false;
    let dur: number | null = null;
    let res: string | null = null;
    let sourcePath: string | null = null;
    if (parsed.kind === "gdrive") {
      const cachePath = path.join(cacheDir, `${parsed.gdriveId}.${parsed.ext}`);
      cached = existsSync(cachePath);
      if (cached) {
        const mediaName = `${alias}.${parsed.ext}`;
        const mediaLink = path.join(mediaDir, mediaName);
        if (!existsSync(mediaLink)) symlinkSync(cachePath, mediaLink);
        const probed = probe(cachePath);
        dur = probed.duration; res = `${probed.width}x${probed.height}`;
        sourcePath = `media/${mediaName}`;
      }
    }
    // Find which sections use this alias
    const usedIn: string[] = [];
    for (const blk of beatBlocks) {
      for (const a of blk.assignments) {
        if (a.alias === alias) usedIn.push(sectionLabel(blk.id).name);
      }
    }
    return { alias, entry, parsed, cached, dur, res, sourcePath, usedIn };
  });

  const libraryHtml = renderLibraryHtml({
    program: cli.program,
    spec,
    entries: allEntries,
  });
  writeFileSync(path.join(outDir, "library.html"), libraryHtml);

  console.log(`Wrote ${path.relative(root, path.join(outDir, "index.html"))}`);
  console.log(`Wrote ${path.relative(root, path.join(outDir, "library.html"))}`);
  console.log(`Coverage: ${okAssignments}/${totalAssignments} clip slots assigned and cached`);
}

interface LibEntry {
  alias: string;
  entry: string;
  parsed: ParsedRef;
  cached: boolean;
  dur: number | null;
  res: string | null;
  sourcePath: string | null;
  usedIn: string[];
}

function renderLibraryHtml(args: {
  program: string;
  spec: ReturnType<typeof loadProgramSpec>;
  entries: LibEntry[];
}): string {
  const { program, spec, entries } = args;
  const used = entries.filter((e) => e.usedIn.length > 0);
  const unused = entries.filter((e) => e.usedIn.length === 0);

  const card = (e: LibEntry): string => {
    const usedBadges = e.usedIn.length
      ? e.usedIn.map((u) => `<span class="lib-tag used-in">${escape(u)}</span>`).join("")
      : `<span class="lib-tag unused">not used in this video</span>`;
    const statusTag = e.cached
      ? `<span class="lib-tag cached">✓ in cache</span>`
      : `<span class="lib-tag missing">⚠ not cached</span>`;
    const video = e.sourcePath
      ? `<video src="${e.sourcePath}" controls preload="metadata"></video>`
      : `<div class="lib-placeholder">${e.parsed.kind === "gdrive" ? `not pulled from Drive yet · <code>${escape(e.parsed.gdriveId ?? "")}</code>` : escape(e.entry)}</div>`;
    return `
      <div class="lib-card">
        <div class="lib-head">
          <h3>@${escape(e.alias)}</h3>
          ${statusTag}
        </div>
        <div class="lib-meta">
          ${e.dur ? `<span>${e.dur.toFixed(1)}s · ${e.res}</span>` : ""}
          ${e.parsed.kind === "gdrive" ? `<code>drive:${escape(e.parsed.gdriveId ?? "")}</code>` : ""}
        </div>
        ${video}
        <div class="lib-tags">${usedBadges}</div>
      </div>`;
  };

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clip Library — ${escape(spec.name)}</title>
<link href="https://fonts.googleapis.com/css2?family=Work+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --paper: #FAFBFF; --paper-2: #FFFFFF; --ink: #0A0620; --ink-2: #14103A; --ink-3: #4A5468;
    --line: #E6E7F0; --rule: #C9CCE0; --indigo: #3843D0; --indigo-deep: #2832A0;
    --indigo-soft: #E7E9FB; --sky: #8EA1FF; --sky-deep: #5C6FE8; --sky-tint: #F0F3FF;
    --mango: #FC5F36; --green: #1F8F6F; --muted: #6B7388;
    --sans: 'Work Sans', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif;
    --mono: 'JetBrains Mono', 'SF Mono', Menlo, monospace;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; background: var(--paper); color: var(--ink); font-family: var(--sans); -webkit-font-smoothing: antialiased; }
  .container { max-width: 1280px; margin: 0 auto; padding: 32px 24px 96px; }
  header { display: flex; align-items: center; gap: 12px; padding-bottom: 24px; border-bottom: 1px solid var(--line); margin-bottom: 24px; }
  header h1 { margin: 0; font-size: 28px; font-weight: 800; background: linear-gradient(90deg, var(--ink-2), var(--indigo) 60%, var(--sky-deep)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  header .subtitle { color: var(--muted); margin-left: auto; font-size: 14px; }
  .nav-tabs { display: flex; gap: 8px; margin-bottom: 24px; }
  .nav-tabs a { padding: 8px 16px; border-radius: 8px; background: white; border: 1px solid var(--line); text-decoration: none; color: var(--ink-2); font: 600 13px var(--sans); }
  .nav-tabs a.active { background: var(--indigo); color: white; border-color: var(--indigo); }
  .nav-tabs a:hover:not(.active) { background: var(--sky-tint); }
  .lead { padding: 18px 24px; background: linear-gradient(120deg, var(--paper-2) 0%, var(--sky-tint) 100%); border: 1px solid var(--line); border-radius: 14px; margin-bottom: 28px; font-size: 14px; color: var(--ink-2); line-height: 1.55; }
  .lead strong { color: var(--ink); }
  .section-title { display: flex; align-items: baseline; gap: 12px; margin: 28px 0 14px; }
  .section-title h2 { margin: 0; font-size: 20px; }
  .section-title .hint { color: var(--muted); font-size: 13px; }
  .lib-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; }
  .lib-card { background: white; border: 1px solid var(--line); border-radius: 12px; padding: 12px; }
  .lib-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
  .lib-head h3 { margin: 0; font: 700 15px var(--mono); }
  .lib-meta { font: 400 12px var(--mono); color: var(--muted); margin-bottom: 8px; }
  .lib-meta code { background: var(--paper); padding: 1px 4px; border-radius: 3px; }
  .lib-card video { width: 100%; aspect-ratio: 16/9; background: #000; border-radius: 6px; }
  .lib-placeholder { padding: 24px; text-align: center; color: var(--muted); border-radius: 8px; background: var(--paper); border: 1px dashed var(--rule); font-size: 12px; }
  .lib-placeholder code { background: white; padding: 1px 4px; border-radius: 3px; font-family: var(--mono); }
  .lib-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
  .lib-tag { font: 600 11px var(--sans); padding: 2px 8px; border-radius: 999px; }
  .lib-tag.used-in { background: rgba(31,143,111,0.15); color: var(--green); }
  .lib-tag.unused { background: var(--sky-tint); color: var(--muted); }
  .lib-tag.cached { background: rgba(56,67,208,0.1); color: var(--indigo-deep); }
  .lib-tag.missing { background: rgba(252,95,54,0.15); color: var(--mango); }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>${escape(spec.name)} · clip library</h1>
    <span class="subtitle">${program} · ${spec.country_focus} · ${spec.status}</span>
  </header>
  <div class="nav-tabs">
    <a href="/">Per-section review</a>
    <a href="/library.html" class="active">Clip library</a>
  </div>
  <div class="lead">
    This is every video clip registered in the program's manifest — what's been downloaded,
    what's still on Drive, and which sections of the current video they're used in.
    <strong>Want to suggest a new clip?</strong> Drop a Drive link in the feedback box on the
    main page; the agent will pull it into the cache on the next iteration and slot it where
    you indicate.
  </div>

  <div class="section-title">
    <h2>Used in this video (${used.length})</h2>
    <span class="hint">each tag shows which section it's currently placed in</span>
  </div>
  <div class="lib-grid">
    ${used.map(card).join("") || `<div class="lib-placeholder">No clips assigned to any section yet.</div>`}
  </div>

  <div class="section-title">
    <h2>Available but unused (${unused.length})</h2>
    <span class="hint">cached on disk, ready to swap into any section</span>
  </div>
  <div class="lib-grid">
    ${unused.map(card).join("") || `<div class="lib-placeholder">Every cached clip is currently in use.</div>`}
  </div>
</div>
</body>
</html>`;
}

interface UnusedClip {
  alias: string;
  status: string;
  entry: string;
  gdriveId?: string;
  sourcePath?: string;
  sourceDuration?: number;
  sourceRes?: string;
}

function renderHtml(args: {
  program: string;
  spec: ReturnType<typeof loadProgramSpec>;
  timeline: ReturnType<typeof resolveBeats>;
  beatBlocks: BeatBlock[];
  unusedClips: UnusedClip[];
  totalAssignments: number;
  okAssignments: number;
  finalAvailable: boolean;
}): string {
  const { program, spec, timeline, beatBlocks, unusedClips, totalAssignments, okAssignments, finalAvailable } = args;
  const totalSec = timeline.totalFrames / timeline.fps;

  const beatColors: Record<string, string> = {
    intro_hook: "#3843D0",
    intro_cycle: "#5C6FE8",
    intro_handoff: "#8EA1FF",
    body_scene: "#1F8F6F",
    body_problem_stat: "#FC5F36",
    body_product_beats: "#FEAF31",
    body_impact_stats: "#10684F",
    outro_cta: "#2832A0",
  };

  const beatCardsHtml = beatBlocks
    .map((blk) => renderBeatCard(blk, totalSec, beatColors[blk.kind] ?? "#3843D0"))
    .join("\n");

  const timelineHtml = beatBlocks
    .map((blk) => {
      const leftPct = (blk.startSec / totalSec) * 100;
      const widthPct = (blk.durationSec / totalSec) * 100;
      return `<div class="tl-beat" style="left:${leftPct}%;width:${widthPct}%;background:${beatColors[blk.kind] ?? "#3843D0"}" title="${sectionLabel(blk.id).name}: ${fmtTs(blk.startSec)} → ${fmtTs(blk.endSec)}"></div>`;
    })
    .join("");

  // Legend strip above the colored bar so section names never truncate.
  const tlLegendHtml = beatBlocks
    .map((blk) => {
      const color = beatColors[blk.kind] ?? "#3843D0";
      return `<span class="tl-legend-item"><span class="dot" style="background:${color}"></span>${escape(sectionLabel(blk.id).name)}</span>`;
    })
    .join("");

  const unusedHtml = unusedClips
    .map((u) => {
      const status = u.status === "ok" ? "ok" : u.status === "missing-cache" ? "missing" : "non-gdrive";
      const badge =
        u.status === "ok"
          ? "✓ cached"
          : u.status === "missing-cache"
            ? "⚠ not in cache"
            : "literal";
      const video =
        u.status === "ok"
          ? `<video src="${u.sourcePath}" controls preload="metadata"></video>`
          : `<div class="placeholder">${badge}</div>`;
      return `
      <div class="card unused">
        <div class="card-header">
          <h3>@${u.alias}</h3>
          <span class="badge ${status}">${badge}</span>
        </div>
        <div class="meta">
          ${u.sourceDuration ? `${u.sourceDuration.toFixed(1)}s · ${u.sourceRes}` : ""}
          ${u.gdriveId ? `<br/><code>gdrive:${u.gdriveId}</code>` : ""}
        </div>
        ${video}
      </div>`;
    })
    .join("");

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clip Explorer — ${escape(spec.name)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Work+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --paper: #FAFBFF;
    --paper-2: #FFFFFF;
    --ink: #0A0620;
    --ink-2: #14103A;
    --ink-3: #4A5468;
    --line: #E6E7F0;
    --rule: #C9CCE0;
    --indigo: #3843D0;
    --indigo-deep: #2832A0;
    --indigo-soft: #E7E9FB;
    --sky: #8EA1FF;
    --sky-deep: #5C6FE8;
    --sky-tint: #F0F3FF;
    --mango: #FC5F36;
    --marigold: #FEAF31;
    --green: #1F8F6F;
    --muted: #6B7388;
    --sans: 'Work Sans', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif;
    --mono: 'JetBrains Mono', 'SF Mono', Menlo, monospace;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--paper); color: var(--ink); font-family: var(--sans); -webkit-font-smoothing: antialiased; }
  .container { max-width: 1280px; margin: 0 auto; padding: 24px 24px 96px; }
  header { display: flex; align-items: center; gap: 12px; padding-bottom: 16px; border-bottom: 1px solid var(--line); margin-bottom: 16px; flex-wrap: wrap; }
  header h1 { margin: 0; font-size: 22px; font-weight: 800; letter-spacing: -0.02em; background: linear-gradient(90deg, var(--ink-2), var(--indigo) 60%, var(--sky-deep)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  header .subtitle { color: var(--muted); margin-left: auto; font-size: 13px; }
  .coverage { display: inline-block; padding: 3px 9px; border-radius: 999px; background: var(--indigo-soft); color: var(--indigo-deep); font-weight: 600; font-size: 12px; margin-left: 10px; }
  .hero { padding: 18px; background: white; border: 1px solid var(--line); border-radius: 18px; margin-bottom: 20px; }
  .hero video { width: 100%; aspect-ratio: 16/9; background: #000; border-radius: 12px; display: block; }
  .hero-line { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 12px; font-size: 13px; color: var(--ink-3); }
  .hero-line .sep { color: var(--rule); }
  .hero-line strong { color: var(--ink-2); font-weight: 600; }
  /* Beat timeline: legend strip ABOVE the colored bar so labels never truncate. */
  .timeline-wrap { margin-top: 12px; }
  .tl-legend { display: flex; flex-wrap: wrap; gap: 8px 14px; margin-bottom: 8px; font-size: 11px; color: var(--ink-3); }
  .tl-legend-item { display: inline-flex; align-items: center; gap: 6px; }
  .tl-legend-item .dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
  .timeline { display: flex; height: 14px; border-radius: 4px; overflow: hidden; border: 1px solid var(--line); position: relative; background: var(--sky-tint); }
  .tl-beat { position: absolute; top: 0; bottom: 0; opacity: 0.92; cursor: default; }
  .section-title { display: flex; align-items: baseline; gap: 12px; margin: 24px 0 12px; }
  .section-title h2 { margin: 0; font-size: 18px; font-weight: 700; color: var(--ink); }
  .section-title .hint { color: var(--muted); font-size: 12px; }
  .beats { display: grid; grid-template-columns: 1fr; gap: 12px; }
  .beat { background: white; border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; }
  .beat-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
  .beat-kind-dot { width: 10px; height: 10px; border-radius: 999px; flex-shrink: 0; }
  .beat-head h3 { margin: 0; font-size: 16px; font-weight: 700; }
  .beat-head h3 .time { color: var(--muted); font-family: var(--mono); font-size: 10px; font-weight: 500; margin-left: 4px; }
  .beat-head .narration { max-width: 380px; color: var(--ink-3); font-size: 13px; font-style: italic; text-align: right; line-height: 1.4; }
  .assignments { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
  .card { background: var(--sky-tint); border: 1px solid var(--line); border-radius: 12px; padding: 10px; }
  .card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .card-header h3 { margin: 0; font-size: 15px; font-weight: 600; font-family: var(--mono); }
  .card-header .role { color: var(--muted); font-size: 11px; }
  .badge { padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; margin-left: auto; }
  .badge.ok { background: rgba(31, 143, 111, 0.15); color: var(--green); }
  .badge.missing { background: rgba(252, 95, 54, 0.15); color: var(--mango); }
  .badge.unknown { background: rgba(254, 175, 49, 0.18); color: #B47800; }
  .badge.literal { background: var(--indigo-soft); color: var(--indigo-deep); }
  .badge.non-gdrive { background: var(--indigo-soft); color: var(--indigo-deep); }
  .meta { font-size: 12px; color: var(--muted); margin-bottom: 8px; font-family: var(--mono); }
  .meta code { background: white; padding: 1px 4px; border-radius: 3px; }
  .clip-wrapper { position: relative; }
  .clip-wrapper video { width: 100%; aspect-ratio: 16/9; background: #000; border-radius: 8px; display: block; }
  .clip-meter { position: relative; margin-top: 6px; height: 18px; background: var(--paper); border-radius: 6px; border: 1px solid var(--rule); overflow: hidden; }
  .clip-meter .full { position: absolute; inset: 0; }
  .clip-meter .used { position: absolute; top: 0; bottom: 0; background: var(--indigo); border-right: 2px solid var(--ink-2); }
  .clip-meter .used::after { content: 'IN FINAL VIDEO'; position: absolute; right: 4px; top: 50%; transform: translateY(-50%); color: white; font-size: 9px; font-weight: 700; letter-spacing: 0.06em; }
  .clip-meter-legend { font-size: 11px; color: var(--muted); display: flex; justify-content: space-between; margin-top: 4px; gap: 12px; }
  .clip-meter-legend span:nth-child(2) { color: var(--ink-3); font-weight: 500; text-align: center; flex: 1; }
  .clip-meter-legend span:nth-child(1), .clip-meter-legend span:nth-child(3) { font-family: var(--mono); font-size: 10px; }
  .placeholder { padding: 24px; text-align: center; color: var(--muted); border-radius: 8px; background: white; border: 1px dashed var(--rule); }
  .no-asset { padding: 16px; text-align: center; color: var(--muted); font-size: 13px; border: 1px dashed var(--rule); border-radius: 10px; }
  .unused-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }
  .unused.card video { width: 100%; aspect-ratio: 16/9; background: #000; border-radius: 8px; }
  .footer-help { margin-top: 48px; padding: 20px; background: var(--indigo-soft); border-radius: 14px; font-size: 13px; color: var(--ink-2); }
  .footer-help code { background: white; padding: 1px 6px; border-radius: 4px; font-family: var(--mono); }
  /* Drag-and-drop targets (hidden until a clip is being dragged) */
  .drop-hint { display: none; padding: 6px 10px; margin-bottom: 8px; text-align: center; font: 600 11px var(--sans); color: var(--indigo-deep); background: rgba(56,67,208,0.1); border: 1px dashed var(--indigo); border-radius: 6px; }
  body.dragging-clip .card[data-droppable] .drop-hint { display: block; }
  .card[data-droppable].drag-over { box-shadow: 0 0 0 3px var(--indigo); background: var(--sky-tint); }
  .section-subtitle { color: var(--muted); font-size: 12px; margin-top: 1px; }
  /* Drawer toggle — primary action, stands apart from the tabs */
  .nav-tabs .drawer-toggle { margin-left: auto; padding: 8px 14px; border-radius: 8px; background: var(--ink-2); color: white; border: none; font: 700 13px var(--sans); cursor: pointer; display: inline-flex; align-items: center; gap: 8px; transition: background 0.15s, transform 0.15s; }
  .nav-tabs .drawer-toggle:hover { background: var(--ink); transform: translateY(-1px); }
  .nav-tabs .drawer-toggle:active { transform: translateY(0); }
  /* Library side drawer panel — slides in from the right */
  .drawer-backdrop { position: fixed; inset: 0; background: rgba(10, 6, 32, 0.42); opacity: 0; pointer-events: none; transition: opacity 0.18s; z-index: 50; }
  .drawer-backdrop.open { opacity: 1; pointer-events: auto; }
  .drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(460px, 90vw); background: white; box-shadow: -16px 0 40px rgba(10,6,32,0.18); transform: translateX(100%); transition: transform 0.22s ease-out; z-index: 60; display: flex; flex-direction: column; }
  .drawer.open { transform: translateX(0); }
  .drawer-head { display: flex; align-items: center; gap: 8px; padding: 16px 18px; border-bottom: 1px solid var(--line); }
  .drawer-head h2 { margin: 0; font-size: 16px; }
  .drawer-head button { margin-left: auto; background: none; border: 1px solid var(--rule); color: var(--ink-2); padding: 4px 10px; border-radius: 6px; cursor: pointer; font: 600 12px var(--sans); }
  .drawer-help { padding: 10px 18px; background: var(--sky-tint); font: 400 12px var(--sans); color: var(--ink-3); border-bottom: 1px solid var(--line); line-height: 1.4; }
  .drawer-help strong { color: var(--ink-2); }
  .drawer-list { flex: 1; overflow: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
  .drawer-card { background: var(--paper); border: 1px solid var(--line); border-radius: 10px; padding: 10px; cursor: grab; transition: box-shadow 0.12s, transform 0.12s; }
  .drawer-card:hover { box-shadow: 0 4px 14px rgba(10,6,32,0.08); transform: translateY(-1px); }
  .drawer-card.dragging { opacity: 0.5; cursor: grabbing; }
  .drawer-card video { width: 100%; aspect-ratio: 16/9; background: #000; border-radius: 6px; pointer-events: none; }
  .drawer-card-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
  .drawer-card-head h4 { margin: 0; font: 700 13px var(--mono); }
  .drawer-card-meta { font: 400 11px var(--mono); color: var(--muted); margin: 4px 0; }
  .drawer-card .drag-handle { font-size: 12px; color: var(--muted); margin-left: auto; }
  .lib-tag { font: 600 11px var(--sans); padding: 2px 8px; border-radius: 999px; }
  .lib-tag.used-in { background: rgba(31,143,111,0.15); color: var(--green); }
  .lib-tag.unused { background: var(--sky-tint); color: var(--muted); }
  .lib-placeholder { padding: 16px; text-align: center; color: var(--muted); border-radius: 8px; background: var(--paper); border: 1px dashed var(--rule); font: 400 12px var(--sans); }
  /* Feedback widgets */
  .fb-toggle { margin-left: auto; background: white; border: 1px solid var(--rule); color: var(--ink-2); cursor: pointer; padding: 4px 10px; font: 600 11px var(--sans); border-radius: 999px; }
  .fb-toggle:hover { background: var(--paper); }
  .fb-toggle.active { background: var(--indigo); color: white; border-color: var(--indigo); }
  .fb-panel { display: none; margin-top: 12px; padding: 12px; background: white; border: 1px solid var(--line); border-radius: 10px; }
  .fb-panel.open { display: block; }
  .fb-panel textarea { width: 100%; min-height: 80px; padding: 8px 10px; font: 400 13px var(--sans); border: 1px solid var(--rule); border-radius: 6px; resize: vertical; }
  .fb-panel .fb-row { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
  .fb-panel .fb-row .ts-grab { font: 500 11px var(--mono); color: var(--muted); }
  .fb-panel button.fb-save { background: var(--indigo); color: white; border: none; padding: 6px 14px; font: 600 12px var(--sans); border-radius: 6px; cursor: pointer; }
  .fb-panel button.fb-save:hover { background: var(--indigo-deep); }
  .fb-status { font-size: 11px; color: var(--muted); }
  .global-fb { margin: 24px 0; padding: 14px 16px; background: white; border: 1px solid var(--line); border-radius: 12px; }
  .global-fb h3 { margin: 0 0 6px; font-size: 14px; color: var(--ink-2); display: flex; align-items: center; gap: 8px; font-weight: 700; }
  .global-fb .hint { font-size: 12px; color: var(--muted); margin-bottom: 10px; line-height: 1.4; }
  .fb-log { margin-top: 16px; padding: 12px; background: var(--paper); border-radius: 8px; max-height: 240px; overflow: auto; font: 400 12px var(--mono); white-space: pre-wrap; color: var(--ink-2); }
  .fb-log:empty { display: none; }
  .range-row { display: grid; grid-template-columns: auto 1fr auto auto auto; gap: 10px; align-items: center; margin-top: 8px; padding: 8px 12px; background: white; border: 1px solid var(--line); border-radius: 8px; }
  .range-row label { font-size: 12px; font-weight: 600; color: var(--ink-2); }
  .range-row input[type=range] { width: 100%; height: 4px; -webkit-appearance: none; background: var(--rule); border-radius: 999px; outline: none; }
  .range-row input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; appearance: none; width: 18px; height: 18px; border-radius: 50%; background: var(--indigo); cursor: pointer; border: 3px solid white; box-shadow: 0 1px 4px rgba(0,0,0,0.2); }
  .range-row .range-val { font-size: 12px; color: var(--ink-3); font-family: var(--mono); white-space: nowrap; }
  .range-row .range-val strong { color: var(--indigo-deep); font-family: var(--sans); font-weight: 700; }
  .range-row button.btn-save-range { background: var(--indigo); color: white; border: none; padding: 6px 12px; font: 600 12px var(--sans); border-radius: 6px; cursor: pointer; }
  .range-row button.btn-save-range:hover { background: var(--indigo-deep); }
  .range-row button.btn-save-range:disabled { background: var(--rule); color: var(--muted); cursor: not-allowed; }
  .clip-meter-legend .legend-mid { color: var(--ink-3); font-weight: 500; flex: 1; text-align: center; }
  .nav-tabs { display: flex; gap: 8px; margin-bottom: 24px; }
  .nav-tabs a { padding: 8px 16px; border-radius: 8px; background: white; border: 1px solid var(--line); text-decoration: none; color: var(--ink-2); font: 600 13px var(--sans); }
  .nav-tabs a.active { background: var(--indigo); color: white; border-color: var(--indigo); }
  .nav-tabs a:hover:not(.active) { background: var(--sky-tint); }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>${escape(spec.name)} · clip review</h1>
    <span class="coverage">${okAssignments}/${totalAssignments} video clips assigned</span>
    <span class="subtitle">${program} · ${spec.country_focus} · ${spec.status}</span>
  </header>

  <div class="nav-tabs">
    <a href="/" class="active">Per-section review</a>
    <a href="/library.html">Clip library</a>
    <button class="drawer-toggle" id="open-drawer">📚 Open library drawer</button>
  </div>

  <div class="hero">
    ${finalAvailable
      ? `<video src="media/final.mp4" controls preload="metadata" id="final-video"></video>`
      : `<div class="placeholder">No rendered video yet. Run <code>npm run render -- --program=${program}</code>.</div>`}
    <div class="hero-line">
      <strong>${escape(spec.country_focus)}</strong>
      <span class="sep">·</span>
      <span>${escape(spec.status)}</span>
      <span class="sep">·</span>
      <span>${fmtTs(totalSec)} long</span>
      <span class="sep">·</span>
      <span>${timeline.beats.length} sections</span>
      <span class="sep">·</span>
      <span>${Object.keys(spec.manifest ?? {}).length} clips in manifest</span>
    </div>
    <div class="timeline-wrap">
      <div class="tl-legend">${tlLegendHtml}</div>
      <div class="timeline" id="timeline">${timelineHtml}</div>
    </div>
  </div>

  <div class="section-title">
    <h2>Sections</h2>
    <span class="hint">click play on any clip to see what's in it. the blue bar = the portion that appears in the final video.</span>
  </div>
  <div class="beats">
    ${beatCardsHtml}
  </div>

  <div class="section-title">
    <h2>Available clips not currently used</h2>
    <span class="hint">cached and ready to drag into any section above</span>
  </div>
  <div class="unused-grid">
    ${unusedHtml || '<div class="no-asset">All manifest entries are in use.</div>'}
  </div>

  <div class="global-fb">
    <h3>💬 Overall feedback on this video</h3>
    <div class="hint">Pause the player above at a moment you want to flag, hit <strong>use current video time</strong>, then describe what should change. Saved to <code>feedback.md</code> for the next iteration.</div>
    <textarea id="fb-global" placeholder="e.g., music gets too loud during field footage; 1M+ stat should be bigger; swap village clip for a wider shot..."></textarea>
    <div class="fb-row">
      <button class="fb-toggle" id="fb-grab-time">use current video time</button>
      <span class="ts-grab" id="fb-grab-time-out">no timestamp tagged yet</span>
      <button class="fb-save" data-target="global">save feedback</button>
      <span class="fb-status" id="fb-global-status"></span>
    </div>
  </div>

  <div class="section-title">
    <h2>Feedback log</h2>
    <span class="hint">this session — also persisted to <code>feedback.md</code></span>
  </div>
  <div class="fb-log" id="fb-log"></div>

  <div class="footer-help">
    <strong>Want to suggest a better clip for a beat?</strong>
    Send a Drive link or a YouTube reference for any beat marked
    <em>no clip</em> or where the current one doesn't fit. Then run
    <code>npm run hydrate -- --program=${program}</code> to seed the
    cache, edit <code>programs/${program}.yaml</code>, and re-render.
  </div>
</div>

<!-- Library side drawer -->
<div class="drawer-backdrop" id="drawer-backdrop"></div>
<aside class="drawer" id="drawer">
  <div class="drawer-head">
    <h2>📚 Clip library</h2>
    <button id="close-drawer">close</button>
  </div>
  <div class="drawer-help">
    <strong>Drag a clip onto any section card</strong> to swap it in. The
    section's slot will update, hydrate runs automatically, and a re-render
    kicks off in the background.
  </div>
  <div class="drawer-list" id="drawer-list">
    <!-- populated at runtime from the library API -->
    <div style="text-align: center; color: var(--muted); padding: 24px;">Loading…</div>
  </div>
</aside>

<script>
  const finalVideo = document.getElementById('final-video');
  const grabBtn = document.getElementById('fb-grab-time');
  const grabOut = document.getElementById('fb-grab-time-out');
  let grabbedTs = null;
  if (grabBtn) {
    grabBtn.addEventListener('click', () => {
      if (!finalVideo) return;
      grabbedTs = finalVideo.currentTime;
      grabOut.textContent = grabbedTs.toFixed(1) + 's';
    });
  }
  // Toggle per-beat feedback panels
  document.querySelectorAll('.fb-toggle[data-beat]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const beatId = btn.dataset.beat;
      const panel = document.querySelector('.fb-panel[data-beat="' + beatId + '"]');
      const isOpen = panel.classList.toggle('open');
      btn.classList.toggle('active', isOpen);
    });
  });

  async function saveFeedback(payload, statusEl, textarea) {
    statusEl.textContent = 'saving…';
    try {
      const resp = await fetch('/feedback', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      statusEl.textContent = '✓ saved at ' + data.timestamp;
      textarea.value = '';
      refreshLog();
    } catch (e) {
      statusEl.textContent = '⚠ error: ' + e.message;
    }
  }

  document.querySelectorAll('button.fb-save').forEach((btn) => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.target;
      const beatId = btn.dataset.beat;
      const textarea = target === 'global'
        ? document.getElementById('fb-global')
        : document.querySelector('.fb-panel[data-beat="' + beatId + '"] textarea');
      const statusEl = target === 'global'
        ? document.getElementById('fb-global-status')
        : document.querySelector('.fb-panel[data-beat="' + beatId + '"] .fb-status');
      const note = (textarea.value || '').trim();
      if (!note) { statusEl.textContent = 'write something first'; return; }
      const payload = {
        scope: target === 'global' ? 'global' : 'beat',
        beatId: beatId || null,
        timestampSec: target === 'global' ? grabbedTs : null,
        note,
      };
      saveFeedback(payload, statusEl, textarea);
    });
  });

  async function refreshLog() {
    try {
      const resp = await fetch('/feedback');
      if (!resp.ok) return;
      const text = await resp.text();
      document.getElementById('fb-log').textContent = text || '(no feedback yet)';
    } catch (e) { /* ignore */ }
  }
  refreshLog();

  // --- Trim handles (Premiere/CapCut-style) ---
  document.querySelectorAll('.card[data-edit-kind]').forEach((card) => {
    const trimBar = card.querySelector('[data-trim]');
    if (!trimBar) return;
    const region = trimBar.querySelector('[data-trim-region]');
    const handleLeft = trimBar.querySelector('[data-trim-handle="left"]');
    const handleRight = trimBar.querySelector('[data-trim-handle="right"]');
    const startDisp = card.querySelector('[data-trim-start]');
    const endDisp = card.querySelector('[data-trim-end]');
    const durDisp = card.querySelector('[data-trim-dur]');
    const saveBtn = card.querySelector('.trim-save');
    const status = card.querySelector('.trim-status');
    const sourceDur = parseFloat(card.dataset.sourceDuration || '0');
    const kind = card.dataset.editKind;
    const index = parseInt(card.dataset.editIndex || '0', 10);

    // Read initial state from inline style %
    function readState() {
      const leftPct = parseFloat(region.style.left || '0');
      const widthPct = parseFloat(region.style.width || '0');
      return { start: (leftPct / 100) * sourceDur, dur: (widthPct / 100) * sourceDur };
    }
    const initial = readState();
    let dirty = false;

    function update(start, dur) {
      const clampedStart = Math.max(0, Math.min(sourceDur - 0.1, start));
      const maxDur = sourceDur - clampedStart;
      const clampedDur = Math.max(0.3, Math.min(maxDur, dur));
      region.style.left = ((clampedStart / sourceDur) * 100).toFixed(3) + '%';
      region.style.width = ((clampedDur / sourceDur) * 100).toFixed(3) + '%';
      startDisp.textContent = clampedStart.toFixed(1);
      endDisp.textContent = (clampedStart + clampedDur).toFixed(1);
      durDisp.textContent = clampedDur.toFixed(1);
      const changed = Math.abs(clampedStart - initial.start) > 0.05 || Math.abs(clampedDur - initial.dur) > 0.05;
      saveBtn.disabled = !changed;
      dirty = changed;
    }

    function makeDrag(target, mode) {
      target.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        const barRect = trimBar.getBoundingClientRect();
        const state = readState();
        const startX = e.clientX;
        const startStart = state.start;
        const startDur = state.dur;
        target.setPointerCapture(e.pointerId);
        function onMove(ev) {
          const dx = ev.clientX - startX;
          const dSec = (dx / barRect.width) * sourceDur;
          if (mode === 'left') {
            const newStart = startStart + dSec;
            const newDur = startDur - dSec;
            update(newStart, newDur);
          } else if (mode === 'right') {
            update(startStart, startDur + dSec);
          } else {
            update(startStart + dSec, startDur);
          }
        }
        function onUp() {
          target.releasePointerCapture(e.pointerId);
          target.removeEventListener('pointermove', onMove);
          target.removeEventListener('pointerup', onUp);
        }
        target.addEventListener('pointermove', onMove);
        target.addEventListener('pointerup', onUp);
      });
    }
    makeDrag(handleLeft, 'left');
    makeDrag(handleRight, 'right');
    makeDrag(region, 'move');

    saveBtn.addEventListener('click', async () => {
      if (!dirty) return;
      const state = readState();
      status.textContent = 'saving…';
      saveBtn.disabled = true;
      try {
        const resp = await fetch('/edit', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            op: 'set-clip-trim',
            kind, index,
            start_seconds: parseFloat(state.start.toFixed(2)),
            duration_seconds: parseFloat(state.dur.toFixed(2)),
          }),
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        status.textContent = '✓ saved · re-rendering in background — refresh the player in a few seconds';
        dirty = false;
      } catch (e) {
        status.textContent = '⚠ ' + e.message;
        saveBtn.disabled = false;
      }
    });
  });

  // --- Inline narration edit (Descript-style) ---
  document.querySelectorAll('[data-narration-beat]').forEach((wrapper) => {
    const beatId = wrapper.dataset.narrationBeat;
    const body = wrapper.querySelector('[data-narration-body]');
    let original = body.textContent.trim();
    body.addEventListener('focus', () => wrapper.classList.add('editing'));
    body.addEventListener('blur', async () => {
      wrapper.classList.remove('editing');
      const current = body.textContent.trim();
      if (current === original) return;
      const label = wrapper.querySelector('.save-hint');
      label.textContent = 'saving…';
      try {
        const resp = await fetch('/edit', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ op: 'set-narration', beatId, text: current }),
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        original = current;
        label.textContent = '✓ saved · re-rendering — refresh the player in a few seconds';
        setTimeout(() => { label.textContent = 'click to edit · click outside to save & re-render'; }, 6000);
      } catch (e) {
        label.textContent = '⚠ ' + e.message;
      }
    });
    body.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { body.textContent = original; body.blur(); }
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); body.blur(); }
    });
  });

  // --- Library drawer + drag-from-library to swap ---
  const drawer = document.getElementById('drawer');
  const backdrop = document.getElementById('drawer-backdrop');
  const drawerList = document.getElementById('drawer-list');
  function openDrawer() {
    drawer.classList.add('open');
    backdrop.classList.add('open');
    if (drawerList.dataset.loaded !== '1') loadLibrary();
  }
  function closeDrawer() {
    drawer.classList.remove('open');
    backdrop.classList.remove('open');
  }
  document.getElementById('open-drawer').addEventListener('click', openDrawer);
  document.getElementById('close-drawer').addEventListener('click', closeDrawer);
  backdrop.addEventListener('click', closeDrawer);

  async function loadLibrary() {
    try {
      const resp = await fetch('/library.json');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      drawerList.innerHTML = '';
      for (const e of data.entries) {
        const card = document.createElement('div');
        card.className = 'drawer-card';
        card.draggable = !!e.sourcePath;
        card.dataset.alias = e.alias;
        const usedTag = e.usedIn.length
          ? '<span class="lib-tag used-in">used: ' + e.usedIn.join(', ') + '</span>'
          : '<span class="lib-tag unused">not used</span>';
        const videoEl = e.sourcePath
          ? '<video src="' + e.sourcePath + '" controls preload="metadata" muted></video>'
          : '<div class="lib-placeholder">not cached</div>';
        const metaEl = e.dur ? e.dur.toFixed(1) + 's · ' + (e.res || '') : 'metadata pending';
        card.innerHTML =
          '<div class="drawer-card-head">' +
            '<h4>@' + e.alias + '</h4>' +
            '<span class="drag-handle">⋮⋮</span>' +
          '</div>' +
          videoEl +
          '<div class="drawer-card-meta">' + metaEl + '</div>' +
          '<div class="lib-tags">' + usedTag + '</div>';
        if (card.draggable) {
          card.addEventListener('dragstart', (ev) => {
            ev.dataTransfer.setData('text/plain', e.alias);
            ev.dataTransfer.effectAllowed = 'move';
            card.classList.add('dragging');
            document.body.classList.add('dragging-clip');
          });
          card.addEventListener('dragend', () => {
            card.classList.remove('dragging');
            document.body.classList.remove('dragging-clip');
          });
        }
        drawerList.appendChild(card);
      }
      drawerList.dataset.loaded = '1';
    } catch (err) {
      drawerList.innerHTML = '<div style="color: var(--mango); padding: 16px;">Library load failed: ' + err.message + '</div>';
    }
  }

  // Drop targets on every section's clip cards
  document.querySelectorAll('.card[data-droppable]').forEach((card) => {
    card.addEventListener('dragover', (ev) => {
      ev.preventDefault();
      card.classList.add('drag-over');
    });
    card.addEventListener('dragleave', () => card.classList.remove('drag-over'));
    card.addEventListener('drop', async (ev) => {
      ev.preventDefault();
      card.classList.remove('drag-over');
      const alias = ev.dataTransfer.getData('text/plain');
      if (!alias) return;
      const kind = card.dataset.editKind;
      const index = parseInt(card.dataset.editIndex || '0', 10);
      try {
        const resp = await fetch('/edit', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ op: 'set-clip-asset', kind, index, alias }),
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        // Reload page to show the new clip; the server kicks off a re-render
        // and hydrate so the new clip is materialized.
        setTimeout(() => location.reload(), 400);
      } catch (e) {
        alert('Swap failed: ' + e.message);
      }
    });
  });
</script>
</body>
</html>`;
}

function renderBeatCard(blk: BeatBlock, _totalSec: number, dotColor: string): string {
  const label = sectionLabel(blk.id);
  const friendlyMissing = (m: string): string => {
    if (m.includes("problem stat")) return "No video clip — this section is a big-number graphic.";
    if (m.includes("impact stat")) return "No video clip — this section is two big-number graphics.";
    return m;
  };
  const cardsHtml =
    blk.assignments.length > 0
      ? blk.assignments
          .map((a) => renderAssignmentCard(a))
          .join("\n")
      : blk.missingSlots.length > 0
        ? blk.missingSlots
            .map((m) => `<div class="no-asset">${escape(friendlyMissing(m))}</div>`)
            .join("\n")
        : `<div class="no-asset">No video clips for this section — it's rendered from the brand template (logo, animated graphics, no footage).</div>`;

  return `
    <div class="beat" data-beat-id="${blk.id}">
      <div class="beat-head">
        <span class="beat-kind-dot" style="background:${dotColor}"></span>
        <div style="flex: 1; min-width: 0;">
          <h3>${escape(label.name)} <span class="time">· ${fmtTs(blk.startSec)} → ${fmtTs(blk.endSec)} · ${blk.durationSec.toFixed(1)}s</span></h3>
          <div class="section-subtitle">${escape(label.subtitle)}</div>
        </div>
        <button class="fb-toggle" data-beat="${blk.id}">💬 leave feedback</button>
      </div>
      <div class="narration-edit" data-narration-beat="${blk.id}" title="Click to edit voiceover line">
        <div class="narration-edit-label">
          Voiceover
          <span class="save-hint">click to edit · click outside to save</span>
        </div>
        <div class="narration-edit-body" contenteditable="plaintext-only" data-narration-body>${escape(blk.narration ?? "")}</div>
      </div>
      <div class="assignments">${cardsHtml}</div>
      <div class="fb-panel" data-beat="${blk.id}">
        <textarea placeholder="What's wrong with this section? Wrong clip, awkward timing, the narration line, missing footage — anything."></textarea>
        <div class="fb-row">
          <button class="fb-save" data-target="beat" data-beat="${blk.id}">save feedback</button>
          <span class="fb-status"></span>
        </div>
      </div>
    </div>`;
}

function renderAssignmentCard(a: ClipAssignment): string {
  const badgeClass = a.status === "ok" ? "ok" : a.status === "missing-cache" ? "missing" : a.status === "alias-unknown" ? "unknown" : "literal";
  const badgeLabel =
    a.status === "ok"
      ? "✓ cached"
      : a.status === "missing-cache"
        ? "⚠ not in cache"
        : a.status === "alias-unknown"
          ? "⚠ alias not in manifest"
          : "literal path";

  if (a.status !== "ok") {
    return `
      <div class="card">
        <div class="card-header">
          <h3>${a.alias ? `@${a.alias}` : a.refRaw}</h3>
          <span class="badge ${badgeClass}">${badgeLabel}</span>
        </div>
        <div class="meta">role: ${a.role}${a.gdriveId ? ` · <code>gdrive:${a.gdriveId}</code>` : ""}</div>
        <div class="placeholder">${
          a.status === "missing-cache"
            ? `Run <code>npm run hydrate</code> to pull the file into the cache.`
            : a.status === "alias-unknown"
              ? `Add this alias to spec.manifest in the YAML.`
              : `Literal path — no preview generated.`
        }</div>
      </div>`;
  }

  const dur = a.sourceDuration ?? 0;
  const usedDur = a.usedDurationSec;
  const usedStart = a.usedStartSec;
  const editAttrs = a.editScope
    ? `data-edit-kind="${a.editScope.kind}" data-edit-index="${a.editScope.index}" data-source-duration="${dur}" data-droppable="1"`
    : "";
  return `
    <div class="card" ${editAttrs}>
      <div class="drop-hint">Drop a clip from the library to replace this one</div>
      <div class="card-header">
        <h3>@${a.alias}</h3>
        <span class="badge ok">${badgeLabel}</span>
      </div>
      <div class="meta">clip is ${dur.toFixed(1)}s long · ${a.sourceRes}${a.gdriveId ? ` · drive id <code>${a.gdriveId}</code>` : ""}</div>
      <div class="clip-wrapper">
        <video src="${a.sourcePath}" controls preload="metadata" class="clip-video"></video>
        ${a.editScope ? renderTrimWidget(dur, usedStart, usedDur) : ""}
      </div>
    </div>`;
}

function renderTrimWidget(sourceDur: number, start: number, dur: number): string {
  const leftPct = sourceDur > 0 ? (start / sourceDur) * 100 : 0;
  const widthPct = sourceDur > 0 ? (dur / sourceDur) * 100 : 0;
  return `
    <div class="trim-bar" data-source-duration="${sourceDur}" data-trim>
      <div class="trim-region" data-trim-region style="left:${leftPct.toFixed(3)}%;width:${widthPct.toFixed(3)}%">
        <div class="trim-handle left" data-trim-handle="left"></div>
        <div class="trim-handle right" data-trim-handle="right"></div>
      </div>
    </div>
    <div class="trim-readout">
      <span>clip start (0.0s)</span>
      <span><strong data-trim-start>${start.toFixed(1)}</strong>s → <strong data-trim-end>${(start + dur).toFixed(1)}</strong>s · <strong data-trim-dur>${dur.toFixed(1)}</strong>s in final video</span>
      <span>clip end (${sourceDur.toFixed(1)}s)</span>
    </div>
    <div class="trim-save-row">
      <button class="trim-save" disabled>save & re-render</button>
      <span class="fb-status trim-status"></span>
      <span style="color: var(--muted); font-size: 11px; margin-left: auto;">drag the handles to trim · drag the middle to slide the window</span>
    </div>`;
}

function escape(s: string): string {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

main();

// Silence "unused" warnings for symlink/copy helpers that future iterations may use.
void copyFileSync;
