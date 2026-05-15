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
  if (Math.abs(sum - defaults.total_seconds) > 0.001) {
    throw new Error(
      `Beat seconds sum to ${sum}, expected ${defaults.total_seconds}. Adjust overrides.`
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
