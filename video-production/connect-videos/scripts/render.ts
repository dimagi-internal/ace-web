#!/usr/bin/env tsx
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import { execSync } from "node:child_process";
import { loadProgramSpec, resolveActiveByBeat } from "../src/lib/spec.node";
import { loadDefaults, resolveBeats, effectiveBeatsForSpec, type ResolvedTimeline, type ResolvedBeat } from "../src/lib/beats.node";
import { resolveRun, specPath, outputPath } from "../src/lib/runs.node";
import { synthesize, synthesizePerBeat, readAlignment, wordStartSeconds, type PerBeatNarration } from "../src/lib/voiceover";
import { estimateCaptionTimeline, captionsFromBeats } from "../src/lib/captions";
import { resolveAssetRefs, formatMissingError } from "../src/lib/asset-resolver.node";

/**
 * Probe an audio file's duration in seconds via ffprobe. Returns 0 on
 * any failure (caller treats 0 as "no extension needed"). Used by the
 * audio-aligned beat realignment below.
 */
function probeAudioDurationSeconds(audioPath: string): number {
  try {
    const out = execSync(
      `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 ${JSON.stringify(audioPath)}`,
      { stdio: ["ignore", "pipe", "ignore"] },
    ).toString().trim();
    const n = parseFloat(out);
    return Number.isFinite(n) && n > 0 ? n : 0;
  } catch {
    return 0;
  }
}

/**
 * Mutate the timeline so every beat with synthesized narration is at
 * least as long as its audio (+ safety margin). Subsequent beats shift
 * later. Total runtime grows by however much the over-budget beats
 * needed.
 *
 * This is the fix for the "narration text gets cut off mid-word" class
 * of issue: even when the agent stays within the prompt's word budget,
 * ElevenLabs' actual pacing varies (~135-165 wpm depending on text),
 * and the rendered audio can run a fraction of a second over its beat.
 * The atrim filter in the mux step then clips the last syllable.
 */
function realignTimelineToAudio(
  timeline: ResolvedTimeline,
  perBeat: PerBeatNarration[],
  safetyMarginSeconds = 0.25,
): ResolvedTimeline {
  if (perBeat.length === 0) return timeline;
  const audioDur = new Map<string, number>();
  for (const n of perBeat) {
    const d = probeAudioDurationSeconds(n.audioPath);
    if (d > 0) audioDur.set(n.beatId, d);
  }
  let extended = false;
  let cursor = 0;
  const beats: ResolvedBeat[] = timeline.beats.map((b) => {
    const ad = audioDur.get(b.id);
    let durSec = b.seconds;
    if (ad !== undefined && ad + safetyMarginSeconds > durSec) {
      durSec = ad + safetyMarginSeconds;
      extended = true;
      console.log(
        `  beat "${b.id}": ${b.seconds.toFixed(2)}s → ${durSec.toFixed(2)}s ` +
          `(audio ${ad.toFixed(2)}s + ${safetyMarginSeconds}s margin)`,
      );
    }
    const durFrames = Math.round(durSec * timeline.fps);
    const out: ResolvedBeat = {
      ...b,
      seconds: durSec,
      startFrame: cursor,
      durationFrames: durFrames,
    };
    cursor += durFrames;
    return out;
  });
  if (extended) {
    console.log(
      `Audio-aligned: total ${(timeline.totalFrames / timeline.fps).toFixed(2)}s → ` +
        `${(cursor / timeline.fps).toFixed(2)}s`,
    );
  }
  return { fps: timeline.fps, totalFrames: cursor, beats };
}

interface CliArgs {
  program: string;
  draft: boolean;
  noVoice: boolean;
  noCaptions: boolean;
  run: string;
}

function parseArgs(): CliArgs {
  const args = process.argv.slice(2);
  const program = args.find((a) => a.startsWith("--program="))?.split("=")[1];
  const run = args.find((a) => a.startsWith("--run="))?.split("=")[1] ?? "";
  if (!program) {
    console.error(
      "Usage: npm run render -- --program=<slug> [--run=<run-NNN>] [--draft] [--no-voice] [--no-captions]"
    );
    process.exit(2);
  }
  return {
    program,
    run,
    draft: args.includes("--draft"),
    noVoice: args.includes("--no-voice"),
    noCaptions: args.includes("--no-captions"),
  };
}

async function main() {
  const cli = parseArgs();
  const root = process.cwd();
  const runId = resolveRun(cli.program, cli.run, root);
  const defaults = loadDefaults(path.join(root, "programs/global_style.yaml"));
  const rawSpec = loadProgramSpec(specPath(cli.program, runId, root));

  // Resolve @manifest aliases -> concrete asset paths and materialize cache
  // entries as symlinks under public/assets/programs/<slug>/. If anything is
  // missing, bail out with a clear hydrate instruction.
  const { spec, missing } = resolveAssetRefs(rawSpec, {
    programSlug: cli.program,
    publicRoot: path.join(root, "public"),
  });
  if (missing.length > 0) {
    console.error(formatMissingError(missing, cli.program));
    process.exit(1);
  }

  // Beats are template/spec-driven, exactly as Root.tsx does for the
  // visuals (effectiveBeatsForSpec): a spec carrying its own `beats:` list
  // (the connect-ddd-walkthrough arc) IS the timeline; otherwise the spec
  // rides the shared global_style.yaml marketing arc with explainer-mode
  // stat-beat filtering. The dropped marketing stat beats sit mid-timeline
  // (problem after scene, impact before outro), so without this the
  // post-scene captions + per-beat voiceover would key off the UNFILTERED
  // offsets and land later than the visuals they narrate. Keeping render's
  // timeline source identical to Root.tsx's keeps audio and visuals in lock
  // step for both arcs.
  let timeline = resolveBeats(effectiveBeatsForSpec(defaults, spec), spec.beat_overrides ?? {});
  const activeByBeat = resolveActiveByBeat(spec);

  if (!spec.narration.script.trim()) {
    console.error(
      `programs/${cli.program}.yaml has empty narration.script. Run "npm run narrate -- --program=${cli.program}" first, or set it manually.`
    );
    process.exit(1);
  }

  // Voiceover — two paths:
  //   - by_beat: synthesize one audio file per beat with non-empty text.
  //     Each beat's audio is placed at its beat's start time. Solves the
  //     "voice ends before video ends" issue because narration is now
  //     anchored to visual structure, not a single packed-from-start blob.
  //   - script-only (legacy): one big VO clip, delayed by start_seconds.
  let voicePath: string | null = null;
  let perBeat: PerBeatNarration[] = [];
  if (!cli.noVoice && spec.voice.provider === "elevenlabs") {
    const apiKey = process.env.ELEVENLABS_API_KEY;
    if (!apiKey) {
      // Hard fail. The previous behaviour (console.warn + render
      // silent) made it possible to ship a "successful" render with
      // no narration — a regression nobody noticed until opening the
      // player. If the spec genuinely calls for voice (elevenlabs
      // provider in spec.yaml), the caller has to either provide a
      // key or opt out explicitly with --no-voice. Silent-by-accident
      // is no longer an option.
      throw new Error(
        "ELEVENLABS_API_KEY not set in environment, but spec.voice.provider=elevenlabs. " +
          "Set ELEVENLABS_API_KEY to render with voice, or pass --no-voice to render silent on purpose."
      );
    } else if (Object.keys(activeByBeat).length > 0) {
      console.log("Synthesizing per-beat voiceover…");
      perBeat = await synthesizePerBeat({
        byBeat: activeByBeat,
        voiceId: spec.voice.voice_id,
        model: spec.voice.model,
        cacheDir: path.join(root, "assets/audio"),
        apiKey,
      });
      console.log(`Per-beat VO ready: ${perBeat.length} clips`);
      // Audio-align: if any synthesized clip is longer than its beat's
      // declared duration, extend that beat (and shift later beats) so
      // the audio plays in full instead of getting cut at the boundary.
      timeline = realignTimelineToAudio(timeline, perBeat);
    } else {
      console.log("Synthesizing voiceover…");
      voicePath = await synthesize({
        script: spec.narration.script,
        voiceId: spec.voice.voice_id,
        model: spec.voice.model,
        cacheDir: path.join(root, "assets/audio"),
        apiKey,
      });
      console.log(`Voiceover ready: ${path.relative(root, voicePath)}`);
    }
  }

  // Narration window — defaults to the full pre-outro span so the VO can
  // start at frame 1 if narration.start_seconds is 0.
  const outroBeat = timeline.beats.find(
    (b) => b.kind === "outro_cta" || b.kind === "outro_card",
  );
  const outroSeconds = outroBeat ? outroBeat.durationFrames / timeline.fps : 0;
  const totalSeconds = timeline.totalFrames / timeline.fps;
  const narrationStartSec = spec.narration.start_seconds;
  const narrationDurationSec =
    spec.narration.duration_seconds ?? Math.max(1, totalSeconds - outroSeconds - narrationStartSec);
  const narrationStartFrame = Math.round(narrationStartSec * timeline.fps);
  // Captions: prefer per-beat text when provided (via resolveActiveByBeat) for
  // tight visual-caption sync. Otherwise fall back to the older
  // sentence-proportional estimator over the full narration window.
  const captions = cli.noCaptions
    ? []
    : Object.keys(activeByBeat).length > 0
      ? captionsFromBeats(timeline.beats, activeByBeat)
      : estimateCaptionTimeline({
          script: spec.narration.script,
          durationSeconds: narrationDurationSec,
          fps: timeline.fps,
          startFrame: narrationStartFrame,
        });

  // Compose props for Remotion.
  // Write props to a temp JSON file so minimist doesn't mis-parse JSON arrays
  // (e.g., `--props={"captions":[]}` confuses minimist's [] detection).
  // Pass the spec YAML through props verbatim. The component prefers
  // it over the static PROGRAMS_REGISTRY lookup, so any slug created
  // via /ace:video-from-program-page renders without a registry edit.
  // Read the raw text directly off disk — the staged spec.yaml has
  // already been written by Django's _stage_spec().
  const specYaml = fs.readFileSync(specPath(cli.program, runId, root), "utf8");
  // beatOverrides reflects any audio-alignment extension above. The
  // Remotion component merges this with spec.beat_overrides before
  // calling resolveBeats so the rendered visuals' beat durations line
  // up with what the mux step expects.
  const beatOverrides: Record<string, { seconds: number }> = {};
  for (const b of timeline.beats) {
    beatOverrides[b.id] = { seconds: b.seconds };
  }

  // Extract cycle-step timestamps from the cycle beat's TTS alignment.
  // ElevenLabs' /with-timestamps endpoint returns per-character start
  // seconds in the synthesized audio. We look up where the four cycle
  // keywords actually start being spoken (case-insensitive stem match:
  // "verif" matches verify/verified, "paid" matches paid/paying) and
  // pass those as concrete numbers to the Cycle component. With these,
  // the highlight transitions on the spoken word — not on a guessed
  // proportional position.
  const cyclePerBeat = perBeat.find((p) => p.beatId === "cycle");
  let cycleStepStartSeconds:
    | { learn?: number; deliver?: number; verify?: number; pay?: number }
    | undefined;
  if (cyclePerBeat) {
    const sidecar = cyclePerBeat.audioPath.replace(/\.mp3$/, ".json");
    const alignment = readAlignment(sidecar);
    if (alignment) {
      cycleStepStartSeconds = {
        learn: wordStartSeconds(alignment, "learn") ?? undefined,
        deliver: wordStartSeconds(alignment, "deliver") ?? undefined,
        verify: wordStartSeconds(alignment, "verif") ?? undefined,
        pay: wordStartSeconds(alignment, "paid") ?? wordStartSeconds(alignment, "pay") ?? undefined,
      };
      console.log("Cycle step timings (seconds into cycle audio):", cycleStepStartSeconds);
    }
  }

  const props = { programSlug: cli.program, specYaml, beatOverrides, captions, cycleStepStartSeconds };
  const tmpPropsFile = path.join(os.tmpdir(), `remotion-props-${Date.now()}.json`);
  fs.writeFileSync(tmpPropsFile, JSON.stringify(props));
  const propsArg = `--props=${JSON.stringify(tmpPropsFile)}`;
  // Intermediate (silent) render writes to a scratch tmp file. The
  // muxed output lands at the run's output.mp4 path so the explorer
  // (and ace-web's served media surface) finds it under
  // programs/<slug>/runs/<runId>/output.mp4.
  const runDir = path.join(root, "programs", cli.program, "runs", runId);
  if (!fs.existsSync(runDir)) fs.mkdirSync(runDir, { recursive: true });
  const intermediateDir = path.join(runDir, ".tmp");
  if (!fs.existsSync(intermediateDir)) fs.mkdirSync(intermediateDir, { recursive: true });
  void safeSha; // git sha is no longer in the filename — runId IS the identity
  const outPath = path.join(intermediateDir, "silent.mp4");
  const muxedFinal = outputPath(cli.program, runId, root);
  const widthHeightArgs = cli.draft ? ["--width=1280", "--height=720"] : [];
  const crf = cli.draft ? "--crf=28" : "--crf=22";

  // Render via remotion CLI. Audio is muxed in a second step via ffmpeg
  // (see below) so we keep the Remotion render purely visual.
  const cmd = [
    "npx remotion render src/Root.tsx ProgramVideo",
    JSON.stringify(outPath),
    propsArg,
    ...widthHeightArgs,
    crf,
  ]
    .filter(Boolean)
    .join(" ");

  console.log(`Rendering → ${path.relative(root, outPath)}…`);
  try {
    execSync(cmd, { stdio: "inherit" });
  } finally {
    // Clean up temp props file
    try { fs.unlinkSync(tmpPropsFile); } catch { /* ignore */ }
  }

  // Mux voiceover (mid-video) and optional music bed (full duration) into
  // the silent Remotion render. Builds the ffmpeg filter graph dynamically
  // based on which audio sources are present.
  if (voicePath || perBeat.length > 0 || defaults.music_bed) {
    const muxed = muxedFinal;
    const voiceOffsetMs = Math.round(narrationStartSec * 1000);

    const inputs: string[] = [`-i ${JSON.stringify(outPath)}`];
    const filterParts: string[] = [];
    const mixLabels: string[] = [];

    if (perBeat.length > 0) {
      // Map each beat narration to its beat's start time. Each clip is
      // hard-capped to its beat duration via atrim so adjacent beats
      // never overlap in the mix — overflow audio is preferred-cut at
      // the beat boundary, which is loud-and-clear feedback to shorten
      // that beat's caption text.
      const beatById = new Map(timeline.beats.map((b) => [b.id, b]));
      for (const n of perBeat) {
        const beat = beatById.get(n.beatId);
        if (!beat) continue;
        const offsetMs = Math.round((beat.startFrame / timeline.fps) * 1000);
        const beatDur = (beat.durationFrames / timeline.fps).toFixed(3);
        inputs.push(`-i ${JSON.stringify(n.audioPath)}`);
        const idx = inputs.length - 1;
        const label = `[v${idx}]`;
        filterParts.push(
          `[${idx}:a]atrim=duration=${beatDur},asetpts=PTS-STARTPTS,adelay=${offsetMs}|${offsetMs},apad${label}`
        );
        mixLabels.push(label);
      }
    } else if (voicePath) {
      inputs.push(`-i ${JSON.stringify(voicePath)}`);
      const voIdx = inputs.length - 1;
      filterParts.push(
        `[${voIdx}:a]adelay=${voiceOffsetMs}|${voiceOffsetMs},apad[vo]`
      );
      mixLabels.push("[vo]");
    }

    if (defaults.music_bed) {
      const mb = defaults.music_bed;
      const musicAbs = path.isAbsolute(mb.asset) ? mb.asset : path.join(root, mb.asset);
      if (!fs.existsSync(musicAbs)) {
        console.warn(
          `music_bed asset not found at ${musicAbs}; skipping music bed.`
        );
      } else {
        // Loop the bed (-stream_loop -1) so it covers the FULL audio-aligned
        // video length, not just one pass of the source track. Before this,
        // a bed shorter than the cut (e.g. the 60s default track under a 76s
        // cut) left the tail playing dry. `mb.duration_seconds` is now only a
        // cap on how much of one source pass to use as the loop unit — the
        // output is always trimmed to `totalSeconds`. A short afade-out keeps
        // the loop seam / ending from hard-cutting.
        inputs.push(`-stream_loop -1 -i ${JSON.stringify(musicAbs)}`);
        const mIdx = inputs.length - 1;
        const dur = totalSeconds;
        const fadeStart = Math.max(0, dur - 1.5);
        filterParts.push(
          `[${mIdx}:a]atrim=start=${mb.start_seconds}:duration=${dur},asetpts=PTS-STARTPTS,volume=${mb.volume_db}dB,afade=t=out:st=${fadeStart}:d=1.5[bg]`
        );
        mixLabels.push("[bg]");
      }
    }

    if (mixLabels.length === 0) {
      // We entered the mux branch because the spec referenced audio
      // sources, but every one of them resolved away (e.g. narration
      // generator is "manual" so no voicePath, perBeat empty, music_bed
      // file missing on disk). Fall back to copying the silent render
      // through as the muxed output so the clip-explorer still has a
      // playable preview at out/<slug>-draft-mux.mp4.
      console.warn(
        `No audio sources resolved — remuxing silent render → ${path.relative(root, muxed)}.`
      );
      // Remux (no transcode) with faststart so the browser can scrub
      // the silent fallback the same as the audio-muxed path.
      execSync(
        `ffmpeg -y -i ${JSON.stringify(outPath)} -c copy -movflags +faststart ${JSON.stringify(muxed)}`,
        { stdio: "inherit" },
      );
    } else {
      const filterComplex =
        mixLabels.length > 1
          ? [
              ...filterParts,
              `${mixLabels.join("")}amix=inputs=${mixLabels.length}:duration=first:dropout_transition=0[mix]`,
            ].join("; ")
          : filterParts.join("; ");

      const mapLabel = mixLabels.length > 1 ? "[mix]" : mixLabels[0];

      const ffmpegCmd = [
        "ffmpeg -y",
        ...inputs,
        `-filter_complex ${JSON.stringify(filterComplex)}`,
        "-c:v copy -c:a aac",
        `-map 0:v:0 -map ${JSON.stringify(mapLabel)}`,
        `-t ${totalSeconds}`,
        // Move the MP4 moov atom (the keyframe/timing index) to the
        // front of the file so the browser can seek as soon as the
        // first chunk arrives. Without this, the moov lands at the
        // end and scrubber clicks no-op until the full file
        // downloads — `preload="auto"` on the <video> masked the
        // worst case but didn't fix it.
        "-movflags +faststart",
        JSON.stringify(muxed),
      ].join(" ");
      console.log(`Muxing audio → ${path.relative(root, muxed)}…`);
      execSync(ffmpegCmd, { stdio: "inherit" });
    }
  } else {
    // No audio sources referenced in the spec at all — fall through to
    // the silent video as the run's output. Remux through ffmpeg
    // (no transcode) with faststart so the browser can scrub it.
    execSync(
      `ffmpeg -y -i ${JSON.stringify(outPath)} -c copy -movflags +faststart ${JSON.stringify(muxedFinal)}`,
      { stdio: "inherit" },
    );
  }

  console.log(`Done → ${path.relative(root, muxedFinal)}`);
}

function safeSha(): string {
  try {
    return execSync("git rev-parse --short HEAD").toString().trim();
  } catch {
    return "nogit";
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
