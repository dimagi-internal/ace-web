import { parse } from "yaml";
import { z } from "zod";

export const BeatKind = z.enum([
  "intro_hook",
  "intro_cycle",
  "intro_handoff",
  "body_scene",
  "body_problem_stat",
  "body_product_beats",
  "body_impact_stats",
  "outro_cta",
]);
export type BeatKind = z.infer<typeof BeatKind>;

export const MusicBedSchema = z.object({
  asset: z.string().min(1),
  start_seconds: z.number().nonnegative().default(0),
  duration_seconds: z.number().positive().optional(),
  volume_db: z.number().default(-22),
});
export type MusicBed = z.infer<typeof MusicBedSchema>;

export const BrandSchema = z.object({
  tagline: z.string().min(1),
  differentiator: z.string().min(1).optional(),
  cycle_steps: z.array(z.string()).length(4),
  cta: z.string().min(1).optional(),
});
export type Brand = z.infer<typeof BrandSchema>;

export const DefaultsSchema = z.object({
  brand: BrandSchema.optional(),
  fps: z.number().int().positive(),
  total_seconds: z.number().positive(),
  beats: z.array(
    z.object({ id: z.string(), kind: BeatKind, seconds: z.number().positive() })
  ).min(1),
  voice: z.object({
    provider: z.enum(["elevenlabs", "none"]),
    voice_id: z.string(),
    model: z.string(),
  }),
  music_bed: MusicBedSchema.optional(),
});
export type Defaults = z.infer<typeof DefaultsSchema>;

export type BeatOverrides = Record<string, { seconds?: number } | undefined>;

export interface ResolvedBeat {
  id: string;
  kind: BeatKind;
  seconds: number;
  startFrame: number;
  durationFrames: number;
}

export interface ResolvedTimeline {
  fps: number;
  totalFrames: number;
  beats: ResolvedBeat[];
}

export function parseDefaults(yamlText: string): Defaults {
  return DefaultsSchema.parse(parse(yamlText));
}

export function resolveBeats(
  defaults: Pick<Defaults, "fps" | "total_seconds" | "beats">,
  overrides: BeatOverrides
): ResolvedTimeline {
  const merged = defaults.beats.map((b) => ({
    ...b,
    seconds: overrides[b.id]?.seconds ?? b.seconds,
  }));
  const sum = merged.reduce((acc, b) => acc + b.seconds, 0);
  // The merged sum may legitimately differ from defaults.total_seconds —
  // the audio-alignment pass in scripts/render.ts extends beats whose
  // synthesized narration overruns its declared duration. We accept the
  // merged sum as the new effective total. The old hard-throw caught
  // operator typos in beat_overrides but was incompatible with the
  // dynamic-duration model; if the deviation is large (>30s) we still
  // surface it as a warning since that suggests a real bug.
  if (Math.abs(sum - defaults.total_seconds) > 30) {
    console.warn(
      `resolveBeats: beat seconds sum to ${sum.toFixed(2)}s vs defaults.total_seconds=${defaults.total_seconds}s ` +
        `(diff ${Math.abs(sum - defaults.total_seconds).toFixed(2)}s). Check beat_overrides for typos.`,
    );
  }
  let cursor = 0;
  const beats: ResolvedBeat[] = merged.map((b) => {
    const durationFrames = Math.round(b.seconds * defaults.fps);
    const out: ResolvedBeat = {
      id: b.id,
      kind: b.kind,
      seconds: b.seconds,
      startFrame: cursor,
      durationFrames,
    };
    cursor += durationFrames;
    return out;
  });
  return { fps: defaults.fps, totalFrames: cursor, beats };
}
