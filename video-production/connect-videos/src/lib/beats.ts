import { parse } from "yaml";
import { z } from "zod";

export const BeatKind = z.enum([
  "intro_hook",
  "intro_cycle",
  "intro_handoff",
  // Optional "how the program is built" beat — the program-designer AI
  // cut. Like the stat beats below, it only renders when the spec opts in
  // (spec.ai_build present AND spec.active_cut === "ai"); filterDefaultsForSpec
  // drops it otherwise.
  "body_ai_build",
  "body_scene",
  "body_problem_stat",
  "body_product_beats",
  "body_impact_stats",
  "outro_cta",
  // Walkthrough-arc kinds (connect-ddd-walkthrough template). `intro_title`
  // is a single title card, `body_walkthrough` plays a RANGE of one
  // master clip full-bleed with a per-beat lower-third, `outro_card`
  // reuses the brand Outro. The marketing arc (intro_hook/cycle/handoff +
  // body_* + outro_cta) and main's connect-explainer (which rides the
  // marketing arc) are unchanged — these are additive, so a template can
  // supply its own `beats:` list selecting whichever arc it needs.
  "intro_title",
  "body_walkthrough",
  "outro_card",
]);
export type BeatKind = z.infer<typeof BeatKind>;

export const MusicBedSchema = z.object({
  asset: z.string().min(1),
  start_seconds: z.number().nonnegative().default(0),
  duration_seconds: z.number().positive().optional(),
  volume_db: z.number().default(-22),
});
export type MusicBed = z.infer<typeof MusicBedSchema>;

export const GlobalTemplateSchema = z.object({
  tagline: z.string().min(1),
  differentiator: z.string().min(1).optional(),
  cycle_steps: z.array(z.string()).length(4),
  cta: z.string().min(1).optional(),
});
export type GlobalTemplate = z.infer<typeof GlobalTemplateSchema>;
// Re-export the legacy name so any in-flight imports keep building
// while the rest of the rename rolls out.
export const BrandSchema = GlobalTemplateSchema;
export type Brand = GlobalTemplate;

export const DefaultsSchema = z.object({
  // New canonical key. Legacy `brand:` is read as a fallback by callers
  // (Root.tsx::resolveBrand) so any in-the-wild spec.yaml that hasn't
  // been migrated still renders.
  global_template: GlobalTemplateSchema.optional(),
  brand: GlobalTemplateSchema.optional(),
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

/**
 * Optional-beat resolution: the global timeline in programs/global_style.yaml
 * carries three opt-in beats that only have anything to render when the
 * spec carries the matching field:
 *
 *   - body_problem_stat  ← spec.problem
 *   - body_impact_stats  ← spec.impact
 *   - body_ai_build      ← spec.ai_build AND spec.active_cut === "ai"
 *
 * All three fields are optional (see spec.ts); when a spec omits one (or,
 * for the AI-build beat, isn't in the AI cut), the corresponding beat must
 * not render. This is the single mechanism behind both "explainer mode"
 * (drop the stat cards) and the program-designer AI/standard cut toggle
 * (one spec carries the ai_build content; flipping active_cut renders or
 * drops just that beat — no duplicated spec).
 *
 * Returns a defaults object whose `beats` array has the orphaned opt-in
 * beats removed AND whose `total_seconds` is recomputed to the surviving
 * beats' sum — so the downstream `resolveBeats` sum invariant (its >30s
 * deviation warning) still holds. Backward compatible: a spec that opts
 * into all three gets the unmodified full timeline; every spec authored
 * before body_ai_build existed lacks `ai_build`, so that beat is always
 * dropped for them and their rendered output is byte-for-byte unchanged.
 */
export function filterDefaultsForSpec<
  T extends Pick<Defaults, "total_seconds" | "beats">
>(
  defaults: T,
  spec: { problem?: unknown; impact?: unknown; ai_build?: unknown; active_cut?: unknown },
): T {
  const hasProblem = spec.problem != null;
  const hasImpact = spec.impact != null;
  // The AI-build beat needs BOTH the content block and the AI cut active.
  // A spec can carry ai_build content while running the standard cut
  // (active_cut !== "ai") — the beat is dropped, so the same spec produces
  // the non-AI cut with one field flip.
  const hasAiBuild = spec.ai_build != null && spec.active_cut === "ai";
  if (hasProblem && hasImpact && hasAiBuild) return defaults; // full timeline, unchanged
  const beats = defaults.beats.filter((b) => {
    if (b.kind === "body_problem_stat" && !hasProblem) return false;
    if (b.kind === "body_impact_stats" && !hasImpact) return false;
    if (b.kind === "body_ai_build" && !hasAiBuild) return false;
    return true;
  });
  const total_seconds = beats.reduce((acc, b) => acc + b.seconds, 0);
  return { ...defaults, beats, total_seconds };
}

/**
 * Resolve the beat timeline for a spec, with structure-belongs-to-the-spec
 * semantics:
 *
 *   - If the spec carries its OWN `beats:` list, that's authoritative and
 *     used verbatim (no optional-beat filtering — the author listed exactly
 *     the beats they want). This is how a template owns its structure; the
 *     global `programs/global_style.yaml` `beats:` is then just the default a
 *     spec inherits when it doesn't define its own.
 *   - Otherwise fall back to the legacy global timeline + optional-beat
 *     filtering (filterDefaultsForSpec). Every existing program spec lacks
 *     `beats:`, so this path is byte-for-byte unchanged for them.
 *
 * Returns the {fps, total_seconds, beats} shape resolveBeats consumes.
 */
export function effectiveBeatsForSpec(
  defaults: Pick<Defaults, "fps" | "total_seconds" | "beats">,
  spec: {
    beats?: { id: string; kind: BeatKind; seconds: number }[];
    problem?: unknown;
    impact?: unknown;
    ai_build?: unknown;
    active_cut?: unknown;
  },
): Pick<Defaults, "fps" | "total_seconds" | "beats"> {
  if (Array.isArray(spec.beats) && spec.beats.length > 0) {
    const beats = spec.beats;
    const total_seconds = beats.reduce((acc, b) => acc + b.seconds, 0);
    return { fps: defaults.fps, total_seconds, beats };
  }
  return filterDefaultsForSpec(defaults, spec);
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
