#!/usr/bin/env tsx
/**
 * map-content.ts — build a content map of a reference video.
 *
 * Given a YouTube URL (Dimagi-owned, --owned), downloads the video and its
 * auto-generated captions, extracts a contact-sheet of thumbnails, and writes
 * a content-map.md alongside the assets. The Markdown file references the
 * contact sheet as an image so the assistant can `Read` it to identify
 * timestamps visually (what's happening at 1:23, is there burned-in text,
 * etc.) — then slice the right segments into program YAML asset slots.
 *
 * Usage:
 *   npm run map-content -- --url=<youtube_url> --out=assets/ingest/<slug>-ref/ --owned [--interval=auto] [--skip-download]
 *
 * Outputs in <out>/:
 *   <video_id>.mkv              # source video (kept for ffmpeg slicing)
 *   <video_id>.en.vtt           # auto-generated English captions (if available)
 *   contact-sheet.jpg           # thumbnails tiled, one frame per <interval>s
 *   transcript.txt              # plain text transcript with [mm:ss] markers
 *   content-map.md              # human-readable index linking all of the above
 */

import { execSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";

interface CliArgs {
  url: string;
  out: string;
  owned: boolean;
  interval: number | "auto";
  skipDownload: boolean;
}

function parseArgs(): CliArgs {
  const args = process.argv.slice(2);
  const url = args.find((a) => a.startsWith("--url="))?.slice("--url=".length);
  const out = args.find((a) => a.startsWith("--out="))?.slice("--out=".length);
  const owned = args.includes("--owned");
  const intervalRaw = args.find((a) => a.startsWith("--interval="))?.slice("--interval=".length);
  const skipDownload = args.includes("--skip-download");

  if (!url || !out) {
    console.error(
      "Usage: npm run map-content -- --url=<yt_url> --out=assets/ingest/<slug>-ref/ --owned [--interval=auto|N] [--skip-download]"
    );
    process.exit(2);
  }
  return {
    url,
    out,
    owned,
    interval: intervalRaw && intervalRaw !== "auto" ? Number(intervalRaw) : "auto",
    skipDownload,
  };
}

function videoIdFromUrl(url: string): string {
  const m = url.match(/[?&]v=([A-Za-z0-9_-]{11})/) ?? url.match(/youtu\.be\/([A-Za-z0-9_-]{11})/);
  if (!m) throw new Error(`Could not extract video ID from ${url}`);
  return m[1];
}

function downloadVideo(url: string, outDir: string) {
  const videoTmpl = path.join(outDir, "%(id)s.%(ext)s");
  // Video + audio merged into mkv; English auto-subs as separate .vtt
  execSync(
    `yt-dlp -f "bv*[height<=1080]+ba/b" -o ${JSON.stringify(videoTmpl)} ${JSON.stringify(url)}`,
    { stdio: "inherit" }
  );
  // Try to grab auto-subs; soft-fail because not all videos have them
  try {
    execSync(
      `yt-dlp --write-auto-sub --sub-lang en --convert-subs vtt --skip-download -o ${JSON.stringify(videoTmpl)} ${JSON.stringify(url)}`,
      { stdio: "inherit" }
    );
  } catch {
    console.warn("Auto-subtitles not available; transcript will be empty.");
  }
}

function probeDuration(videoPath: string): number {
  const out = execSync(
    `ffprobe -v error -show_entries format=duration -of csv=p=0 ${JSON.stringify(videoPath)}`
  ).toString().trim();
  return parseFloat(out);
}

function pickInterval(durationSec: number, requested: number | "auto"): number {
  if (requested !== "auto") return requested;
  // Aim for ~36 thumbnails across the video, snapped to a friendly number.
  const target = durationSec / 36;
  const choices = [5, 10, 15, 20, 30, 60, 90, 120];
  return choices.find((c) => c >= target) ?? Math.ceil(target);
}

interface ContactSheetInfo {
  cols: number;
  rows: number;
  intervalSec: number;
}

function buildContactSheet(
  videoPath: string,
  durationSec: number,
  interval: number,
  outPath: string
): ContactSheetInfo {
  const frames = Math.ceil(durationSec / interval);
  const cols = 4;
  const rows = Math.ceil(frames / cols);
  // fps=1/interval samples one frame every `interval` seconds. We skip the
  // drawtext overlay (ffmpeg's fontconfig is fragile on macOS) and instead
  // compute timestamps from grid position in the Markdown that references
  // this sheet.
  const filter = [
    `fps=1/${interval}`,
    "scale=320:180:force_original_aspect_ratio=decrease",
    "pad=320:180:(ow-iw)/2:(oh-ih)/2:black",
    `tile=${cols}x${rows}:padding=4:color=black`,
  ].join(",");
  execSync(
    `ffmpeg -y -i ${JSON.stringify(videoPath)} -vf ${JSON.stringify(filter)} -frames:v 1 -qscale:v 3 -update 1 ${JSON.stringify(outPath)}`,
    { stdio: "inherit" }
  );
  return { cols, rows, intervalSec: interval };
}

interface Cue {
  startSec: number;
  endSec: number;
  text: string;
}

function parseVtt(vttText: string): Cue[] {
  const cues: Cue[] = [];
  const blocks = vttText.split(/\n\n+/);
  const tsRe =
    /(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2})\.(\d{3})/;
  for (const block of blocks) {
    const lines = block.split("\n").map((l) => l.trim()).filter(Boolean);
    const tsLine = lines.find((l) => tsRe.test(l));
    if (!tsLine) continue;
    const m = tsLine.match(tsRe)!;
    const startSec =
      Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) + Number(m[4]) / 1000;
    const endSec =
      Number(m[5]) * 3600 + Number(m[6]) * 60 + Number(m[7]) + Number(m[8]) / 1000;
    const textLines = lines.filter((l) => !tsRe.test(l) && !/^WEBVTT/i.test(l));
    // Strip inline timing markers like <00:00:01.234><c> from YouTube auto-subs
    const text = textLines
      .join(" ")
      .replace(/<[^>]+>/g, "")
      .replace(/\s+/g, " ")
      .trim();
    if (text) cues.push({ startSec, endSec, text });
  }
  return cues;
}

function dedupeCues(cues: Cue[]): Cue[] {
  // YouTube auto-subs emit each phrase multiple times as it accumulates;
  // keep only cues whose text isn't a strict substring of a later cue.
  const out: Cue[] = [];
  for (let i = 0; i < cues.length; i++) {
    const c = cues[i];
    const nextSame = cues
      .slice(i + 1, i + 4)
      .some((n) => n.text.startsWith(c.text) && n.text.length > c.text.length);
    if (!nextSame) out.push(c);
  }
  return out;
}

function fmtTs(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

function writeTranscript(cues: Cue[], outPath: string) {
  const lines = cues.map((c) => `[${fmtTs(c.startSec)}] ${c.text}`);
  writeFileSync(outPath, lines.join("\n") + "\n");
}

interface ChapterSuggestion {
  startSec: number;
  durationSec: number;
  rationale: string;
}

function suggestClips(cues: Cue[]): ChapterSuggestion[] {
  // Find natural ~5-second windows around mentions of Connect-cycle keywords.
  const keywords = [
    /\b(?:learn(?:ing)?|train(?:ing)?|certif(?:y|ied|ication))\b/i,
    /\b(?:deliver(?:y|ed|ing)?|home\s+visit|frontline)\b/i,
    /\b(?:verif(?:y|ied|ication)|audit|GPS|photo)\b/i,
    /\b(?:pay(?:ment|ing)?|paid|earn(?:ing|ed)?)\b/i,
  ];
  const labels = ["Learn", "Deliver", "Verify", "Pay"];
  const seen = new Set<string>();
  const suggestions: ChapterSuggestion[] = [];
  for (const c of cues) {
    keywords.forEach((kw, i) => {
      if (kw.test(c.text) && !seen.has(labels[i])) {
        seen.add(labels[i]);
        suggestions.push({
          startSec: Math.max(0, c.startSec - 1),
          durationSec: Math.min(6, c.endSec - c.startSec + 2),
          rationale: `${labels[i]} — "${c.text.slice(0, 80)}…"`,
        });
      }
    });
  }
  return suggestions;
}

function writeContentMap(args: {
  url: string;
  videoId: string;
  title: string;
  durationSec: number;
  interval: number;
  contactSheetPath: string;
  transcriptPath: string;
  cues: Cue[];
  suggestions: ChapterSuggestion[];
  outPath: string;
  outDir: string;
  sheetInfo: ContactSheetInfo;
}) {
  const rel = (p: string) => path.relative(args.outDir, p);
  const lines = [
    `# Content map — ${args.title}`,
    "",
    `- **YouTube ID:** \`${args.videoId}\` (${args.url})`,
    `- **Duration:** ${fmtTs(args.durationSec)} (${args.durationSec.toFixed(1)}s)`,
    `- **Thumbnail interval:** ${args.interval}s`,
    `- **Cue count:** ${args.cues.length}`,
    "",
    "## Contact sheet",
    "",
    `![contact sheet](${rel(args.contactSheetPath)})`,
    "",
    `Grid: ${args.sheetInfo.cols} cols × ${args.sheetInfo.rows} rows, one tile every ${args.sheetInfo.intervalSec}s.`,
    "Timestamp at grid cell (row, col) — both 0-indexed — is:",
    "`t = (row * cols + col) * interval`",
    "(reading order: top-left → right, then next row).",
    "Open the image to scrub for sections worth slicing, and check for",
    "burned-in captions, watermarks, or title cards that would bleed into a splice.",
    "",
    "## Cycle-keyword splice suggestions",
    "",
    args.suggestions.length === 0
      ? "_(no Connect-cycle keywords found in transcript)_"
      : args.suggestions
          .map(
            (s) =>
              `- ${s.rationale}\n  - Clip: \`ffmpeg -y -ss ${s.startSec.toFixed(1)} -i <SRC> -t ${s.durationSec.toFixed(1)} -c:v libx264 -preset fast -an <OUT>.mp4\``
          )
          .join("\n"),
    "",
    "## Transcript",
    "",
    `Full transcript with timestamps: [\`${rel(args.transcriptPath)}\`](${rel(args.transcriptPath)})`,
    "",
    "First 40 cues:",
    "",
    "```",
    ...args.cues.slice(0, 40).map((c) => `[${fmtTs(c.startSec)}] ${c.text}`),
    "```",
    "",
  ];
  writeFileSync(args.outPath, lines.join("\n"));
}

function main() {
  const cli = parseArgs();
  if (!cli.owned) {
    console.error(
      "Refusing: pass --owned to confirm the YouTube URL is a Dimagi-owned upload."
    );
    process.exit(1);
  }

  const outDir = path.resolve(cli.out);
  mkdirSync(outDir, { recursive: true });

  const videoId = videoIdFromUrl(cli.url);
  const videoPath = path.join(outDir, `${videoId}.mkv`);
  if (!cli.skipDownload && !existsSync(videoPath)) {
    console.log(`Downloading ${cli.url}…`);
    downloadVideo(cli.url, outDir);
  } else if (existsSync(videoPath)) {
    console.log(`Reusing existing ${path.relative(process.cwd(), videoPath)}.`);
  }

  // yt-dlp may produce .mkv or .mp4 depending on stream availability; resolve.
  const candidates = readdirSync(outDir).filter(
    (f) => f.startsWith(videoId) && /\.(mkv|mp4|webm)$/i.test(f)
  );
  if (candidates.length === 0) {
    throw new Error(`No downloaded video file found for ${videoId} in ${outDir}`);
  }
  const actualVideoPath = path.join(outDir, candidates[0]);

  const durationSec = probeDuration(actualVideoPath);
  const interval = pickInterval(durationSec, cli.interval);
  console.log(
    `Video ${videoId}: ${fmtTs(durationSec)} long; sampling every ${interval}s.`
  );

  const contactSheetPath = path.join(outDir, "contact-sheet.jpg");
  console.log("Building contact sheet…");
  const sheetInfo = buildContactSheet(actualVideoPath, durationSec, interval, contactSheetPath);

  const vttCandidate = readdirSync(outDir).find(
    (f) => f.startsWith(videoId) && /\.en(?:-[A-Za-z-]+)?\.vtt$/i.test(f)
  );
  let cues: Cue[] = [];
  if (vttCandidate) {
    const vttText = readFileSync(path.join(outDir, vttCandidate), "utf8");
    cues = dedupeCues(parseVtt(vttText));
    console.log(`Parsed ${cues.length} transcript cues from ${vttCandidate}.`);
  } else {
    console.warn("No .en.vtt found; transcript will be empty.");
  }

  const transcriptPath = path.join(outDir, "transcript.txt");
  writeTranscript(cues, transcriptPath);

  const suggestions = suggestClips(cues);

  const title = videoId; // best-effort; could fetch via yt-dlp --print but keep simple
  const contentMapPath = path.join(outDir, "content-map.md");
  writeContentMap({
    url: cli.url,
    videoId,
    title,
    durationSec,
    interval,
    contactSheetPath,
    transcriptPath,
    cues,
    suggestions,
    outPath: contentMapPath,
    outDir,
    sheetInfo,
  });

  console.log(`Wrote content map to ${path.relative(process.cwd(), contentMapPath)}.`);
}

main();
