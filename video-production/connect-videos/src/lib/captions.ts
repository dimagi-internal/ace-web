export interface CaptionCue {
  startFrame: number;
  endFrame: number;
  text: string;
}

interface Args {
  script: string;
  durationSeconds: number;
  fps: number;
  startFrame: number;
}

/**
 * Build a caption timeline directly from beat boundaries + per-beat text.
 * This is the preferred path when the spec provides `narration.by_beat`:
 * each caption owns exactly the frames of its beat, so visual and caption
 * stay in sync regardless of how fast or slow the voiceover ends up.
 */
export function captionsFromBeats(
  beats: { startFrame: number; durationFrames: number; id: string }[],
  byBeat: Record<string, string>
): CaptionCue[] {
  const cues: CaptionCue[] = [];
  for (const b of beats) {
    const text = (byBeat[b.id] ?? "").trim();
    if (!text) continue;
    cues.push({
      startFrame: b.startFrame,
      endFrame: b.startFrame + b.durationFrames,
      text,
    });
  }
  return cues;
}

export function estimateCaptionTimeline(args: Args): CaptionCue[] {
  const sentences = args.script
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (sentences.length === 0) return [];
  const totalChars = sentences.reduce((a, s) => a + s.length, 0);
  const totalFrames = Math.round(args.durationSeconds * args.fps);
  let cursor = args.startFrame;
  const cues: CaptionCue[] = [];
  sentences.forEach((s, i) => {
    const share = s.length / totalChars;
    const dur =
      i === sentences.length - 1
        ? args.startFrame + totalFrames - cursor
        : Math.round(totalFrames * share);
    cues.push({ startFrame: cursor, endFrame: cursor + dur, text: s });
    cursor += dur;
  });
  return cues;
}
