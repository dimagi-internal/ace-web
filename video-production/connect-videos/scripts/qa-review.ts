#!/usr/bin/env tsx
/**
 * qa-review.ts — extract per-beat representative frames from a rendered
 * video, align each beat to the narration line(s) playing at that time,
 * and emit a Markdown report the assistant (or a human) can scrub for
 * visual/narrative mismatches.
 *
 * Usage:
 *   npm run qa-review -- --program=chc [--video=out/chc-draft-mux.mp4]
 *
 * Outputs in `out/<slug>-qa/`:
 *   - <NN>-<beat-id>.jpg   one frame per beat, sampled at the midpoint
 *   - report.md            human-readable beat-by-beat critique sheet
 *
 * The assistant's next step is to Read the report and each frame image,
 * then write a section-by-section assessment back to the user with
 * concrete fix proposals (asset swap, timing adjust, narration tweak).
 */

import { execSync } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { loadProgramSpec } from "../src/lib/spec.node";
import { loadDefaults, resolveBeats, type ResolvedBeat } from "../src/lib/beats.node";
import { estimateCaptionTimeline, captionsFromBeats, type CaptionCue } from "../src/lib/captions";

interface CliArgs {
  program: string;
  videoPath: string | null;
}

function parseArgs(): CliArgs {
  const args = process.argv.slice(2);
  const program = args.find((a) => a.startsWith("--program="))?.slice("--program=".length);
  const videoPath = args.find((a) => a.startsWith("--video="))?.slice("--video=".length) ?? null;
  if (!program) {
    console.error(
      "Usage: npm run qa-review -- --program=<slug> [--video=<path-to-mp4>]"
    );
    process.exit(2);
  }
  return { program, videoPath };
}

function fmtTs(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

interface BeatGuidance {
  kind: ResolvedBeat["kind"];
  expectation: string;
}

const GUIDANCE: BeatGuidance[] = [
  {
    kind: "intro_hook",
    expectation:
      "Connect logo + brand-aligned tagline. Should set the program-agnostic frame. Narration introduces Connect.",
  },
  {
    kind: "intro_cycle",
    expectation:
      "Four animated steps: Learn / Deliver / Verify / Pay, indigo circles. Narration walks through them.",
  },
  {
    kind: "intro_handoff",
    expectation:
      "\"Here's how it works for <Program>\" handoff line, program name in indigo.",
  },
  {
    kind: "body_scene",
    expectation:
      "Field/program b-roll establishing the program. Lower-third should name the country / context.",
  },
  {
    kind: "body_problem_stat",
    expectation:
      "Large indigo number + plain-language caption + source line. Stat must match what narration is claiming.",
  },
  {
    kind: "body_product_beats",
    expectation:
      "Phone-frame screen recording of the Connect app showing the step the narration just mentioned (Learn / Deliver / Verify / Pay).",
  },
  {
    kind: "body_impact_stats",
    expectation:
      "1–2 big-number stat cards. Numbers must be present in the program YAML (no hallucination).",
  },
  {
    kind: "outro_cta",
    expectation:
      "Connect lockup on indigo gradient, tagline + CTA URL. Music continues, VO should already be done.",
  },
];

function expectationFor(kind: ResolvedBeat["kind"]): string {
  return GUIDANCE.find((g) => g.kind === kind)?.expectation ?? "—";
}

function main() {
  const cli = parseArgs();
  const root = process.cwd();
  const defaults = loadDefaults(path.join(root, "programs/global_style.yaml"));
  const spec = loadProgramSpec(path.join(root, `programs/${cli.program}.yaml`));
  const timeline = resolveBeats(defaults, spec.beat_overrides ?? {});

  const videoPath = cli.videoPath
    ? path.resolve(cli.videoPath)
    : path.resolve(`out/${cli.program}-draft-mux.mp4`);
  if (!existsSync(videoPath)) {
    console.error(
      `No video found at ${videoPath}. Pass --video=<path> or render first with npm run render -- --program=${cli.program} --draft.`
    );
    process.exit(1);
  }

  const outDir = path.resolve(`out/${cli.program}-qa`);
  mkdirSync(outDir, { recursive: true });

  // Re-derive the caption timeline so each beat can be paired with
  // narration text that overlaps it.
  const outroBeat = timeline.beats.find((b) => b.kind === "outro_cta");
  const outroSeconds = outroBeat ? outroBeat.durationFrames / timeline.fps : 0;
  const totalSeconds = timeline.totalFrames / timeline.fps;
  const narrationStartSec = spec.narration.start_seconds;
  const narrationDurationSec =
    spec.narration.duration_seconds ?? Math.max(1, totalSeconds - outroSeconds - narrationStartSec);
  const captions: CaptionCue[] = spec.narration.by_beat
    ? captionsFromBeats(timeline.beats, spec.narration.by_beat)
    : estimateCaptionTimeline({
        script: spec.narration.script,
        durationSeconds: narrationDurationSec,
        fps: timeline.fps,
        startFrame: Math.round(narrationStartSec * timeline.fps),
      });

  function captionsForBeat(beat: ResolvedBeat): CaptionCue[] {
    const beatEnd = beat.startFrame + beat.durationFrames;
    return captions.filter(
      (c) => c.endFrame > beat.startFrame && c.startFrame < beatEnd
    );
  }

  const sections: string[] = [];
  sections.push(`# QA review — ${spec.name} (${cli.program})`);
  sections.push("");
  sections.push(`**Video:** \`${path.relative(root, videoPath)}\``);
  sections.push(`**Duration:** ${fmtTs(totalSeconds)} • **Beats:** ${timeline.beats.length}`);
  sections.push("");
  sections.push(`**Narration window:** ${fmtTs(narrationStartSec)} → ${fmtTs(narrationStartSec + narrationDurationSec)}`);
  sections.push("");
  sections.push("Each beat below shows a representative frame, the narration");
  sections.push("playing across that beat, and the design expectation. Review");
  sections.push("each block and answer the checklist; flag any that need a fix.");
  sections.push("");

  // Sample three frames per beat at 15%, 50%, 85% so transition/animation
  // artifacts can't hide between samples (the impact-card blank frame
  // slipped past the single-mid-frame v1 because it sat exactly at a
  // stat-1/stat-2 boundary at the beat midpoint).
  const SAMPLES = [
    { name: "early", fraction: 0.15 },
    { name: "mid", fraction: 0.5 },
    { name: "late", fraction: 0.85 },
  ];

  timeline.beats.forEach((beat, idx) => {
    const startSec = beat.startFrame / timeline.fps;
    const endSec = (beat.startFrame + beat.durationFrames) / timeline.fps;

    const frameRefs: string[] = [];
    for (const s of SAMPLES) {
      const sampleSec = startSec + (endSec - startSec) * s.fraction;
      const frameName = `${idx.toString().padStart(2, "0")}-${beat.id}-${s.name}.jpg`;
      const framePath = path.join(outDir, frameName);
      execSync(
        `ffmpeg -y -ss ${sampleSec.toFixed(3)} -i ${JSON.stringify(videoPath)} -frames:v 1 -q:v 2 -update 1 ${JSON.stringify(framePath)}`,
        { stdio: "ignore" }
      );
      // Stats: compute mean luminance to flag near-black frames so the
      // reviewer doesn't have to eyeball every one.
      let warn = "";
      try {
        const stat = execSync(
          `ffmpeg -hide_banner -i ${JSON.stringify(framePath)} -vf "signalstats,metadata=mode=print:key=lavfi.signalstats.YAVG" -f null - 2>&1 | grep -o 'YAVG=[0-9.]*' | tail -1`
        ).toString().trim();
        const m = stat.match(/YAVG=([0-9.]+)/);
        const yavg = m ? Number(m[1]) : NaN;
        if (!Number.isNaN(yavg) && yavg < 16) {
          warn = ` ⚠️ mostly-black frame (Y≈${yavg.toFixed(0)})`;
        }
      } catch {
        /* signalstats is best-effort */
      }
      frameRefs.push(`![${s.name} @ ${fmtTs(sampleSec)}${warn}](${frameName})`);
    }

    const cues = captionsForBeat(beat);
    const narrationText = cues
      .map((c) => c.text)
      .join(" ")
      .trim() || "(silent or outside narration window)";

    sections.push(`## ${idx + 1}. \`${beat.id}\` — ${beat.kind}`);
    sections.push("");
    sections.push(`**Time:** ${fmtTs(startSec)} → ${fmtTs(endSec)} (${beat.seconds.toFixed(1)} s)`);
    sections.push("");
    frameRefs.forEach((r) => sections.push(r + ""));
    sections.push("");
    sections.push(`**Narration during beat:**`);
    sections.push(`> ${narrationText}`);
    sections.push("");
    sections.push(`**Design expectation:** ${expectationFor(beat.kind)}`);
    sections.push("");
    sections.push(`**Checklist:**`);
    sections.push(`- [ ] Visual matches narration playing during beat`);
    sections.push(`- [ ] No burned-in captions/lower-thirds/watermarks bleeding through`);
    sections.push(`- [ ] Brand alignment (colors, fonts, logo placement)`);
    sections.push(`- [ ] Caption legible (if rendered) and matches narration`);
    sections.push(`- [ ] Pacing — beat duration feels right for what's shown`);
    sections.push("");
    sections.push(`**Verdict (fill in):**`);
    sections.push(`- score (1–5): _`);
    sections.push(`- issues: _`);
    sections.push(`- fix proposal: _`);
    sections.push("");
    sections.push("---");
    sections.push("");
  });

  const reportPath = path.join(outDir, "report.md");
  writeFileSync(reportPath, sections.join("\n"));
  console.log(
    `Wrote ${timeline.beats.length} frame(s) + report to ${path.relative(root, outDir)}/`
  );
}

main();
