import { parse } from "yaml";
import { z } from "zod";

const BeatOverrideSchema = z.object({ seconds: z.number().positive() }).partial();

// A clip reference can be a plain string (legacy: "@alias" or path) or
// an object that adds slice metadata. start_seconds = where in the
// source clip to begin playback. duration_seconds = how long this clip
// plays in the section. If duration_seconds isn't set, the renderer
// distributes the section's remaining time equally among clips without
// explicit durations.
const ClipRefSchema = z.union([
  z.string().min(1),
  z.object({
    asset: z.string().min(1),
    start_seconds: z.number().nonnegative().default(0),
    duration_seconds: z.number().positive().optional(),
  }),
]);

const ProductBeatSchema = z.object({
  asset: z.string().min(1),
  caption: z.string().min(1),
  start_seconds: z.number().nonnegative().default(0),
  duration_seconds: z.number().positive().optional(),
});

const StatSchema = z.object({
  big: z.string().min(1),
  caption: z.string().min(1),
  source: z.string().optional(),
});

/**
 * Manifest entries map a local alias to an asset source:
 *   gdrive:<fileId>.<ext>   — fetched via ace-gdrive, cached at
 *                              ~/.cache/connect-videos/<fileId>.<ext>
 *   file:<path>             — plain local path, no resolution needed
 *   <plain path>            — same as file:, legacy form
 * The rest of the spec references entries with `@<alias>`.
 */
const ManifestEntrySchema = z.string().min(1);

export const ProgramSpecSchema = z.object({
  slug: z.string().regex(/^[a-z0-9-]+$/),
  name: z.string().min(1),
  country_focus: z.string().min(1),
  status: z.string().min(1),
  tagline: z.string().min(1),
  program_url: z.string().url(),
  beat_overrides: z.record(z.string(), BeatOverrideSchema).optional(),
  manifest: z.record(z.string(), ManifestEntrySchema).optional(),
  scene: z.object({
    clips: z.array(ClipRefSchema).min(1).max(6),
    lower_third: z.string().min(1),
  }),
  problem: StatSchema,
  product: z.object({
    beats: z.array(ProductBeatSchema).min(1).max(4),
  }),
  impact: z.array(StatSchema).min(2).max(3),
  narration: z.object({
    generator: z.enum(["manual", "anthropic"]),
    prompt_version: z.string().min(1),
    // The full script as one blob — what ElevenLabs synthesizes into VO.
    // For audio purposes this is the source of truth.
    script: z.string(),
    // Where the voiceover starts relative to the video. Default 0
    // (begin at frame 1). Use 15 to start narration only at body.
    start_seconds: z.number().nonnegative().default(0),
    // How long the narration window runs. Defaults at render-time to
    // (total_seconds - outro_seconds) so VO ends before the outro card.
    duration_seconds: z.number().positive().optional(),
    // Optional per-beat caption text. When present, captions follow
    // beat boundaries instead of being estimated proportionally from
    // the script blob. Keys are beat ids (hook, cycle, scene, …); any
    // missing beat falls back to empty caption.
    by_beat: z.record(z.string(), z.string()).optional(),
  }),
  voice: z.object({
    provider: z.enum(["elevenlabs", "none"]),
    voice_id: z.string().min(1),
    model: z.string().min(1),
  }),
});

export type ProgramSpec = z.infer<typeof ProgramSpecSchema>;

export class ProgramSpecError extends Error {
  constructor(message: string, public readonly issues: z.ZodIssue[] = []) {
    super(message);
    this.name = "ProgramSpecError";
  }
}

/**
 * Browser-safe asset resolver: rewrites `@alias` references in a parsed
 * ProgramSpec to public-relative paths under `assets/programs/<slug>/`.
 *
 * Does only string transformation — no filesystem access — so it works in
 * the webpack browser bundle (Remotion Studio + remotion render). The
 * Node-side resolver (`asset-resolver.node.ts`) still owns the cache and
 * symlink materialization. Both must agree on the same alias-to-path
 * convention so a path built here actually exists on disk.
 */
/**
 * Normalized clip reference after manifest rewriting. Always carries an
 * asset path (relative to public/), start_seconds offset, and an
 * optional explicit duration. When duration_seconds is undefined the
 * renderer derives it from the section's remaining unassigned time.
 */
export interface ResolvedClipRef {
  asset: string;
  start_seconds: number;
  duration_seconds?: number;
}

export function applyManifestRefs(spec: ProgramSpec): ProgramSpec {
  const manifest = spec.manifest ?? {};
  const programPublicRel = `assets/programs/${spec.slug}`;

  const rewriteAssetPath = (value: string): string => {
    if (!value.startsWith("@")) return value;
    const alias = value.slice(1);
    const ref = manifest[alias];
    if (!ref) {
      throw new Error(
        `Asset reference "@${alias}" has no entry in spec.manifest of program "${spec.slug}".`
      );
    }
    if (ref.startsWith("gdrive:")) {
      const body = ref.slice("gdrive:".length);
      const dot = body.lastIndexOf(".");
      if (dot <= 0) {
        throw new Error(
          `Manifest entry for "@${alias}" missing extension: "${ref}"`
        );
      }
      const ext = body.slice(dot + 1);
      return `${programPublicRel}/${alias}.${ext}`;
    }
    if (ref.startsWith("file:")) return ref.slice("file:".length);
    return ref; // plain path
  };

  const normalizeClip = (c: ProgramSpec["scene"]["clips"][number]): ResolvedClipRef => {
    if (typeof c === "string") return { asset: rewriteAssetPath(c), start_seconds: 0 };
    return {
      asset: rewriteAssetPath(c.asset),
      start_seconds: c.start_seconds ?? 0,
      duration_seconds: c.duration_seconds,
    };
  };

  // We rebuild scene.clips as an array of normalized objects so the
  // composition can rely on a single shape regardless of YAML form.
  const resolvedScene = {
    ...spec.scene,
    clips: spec.scene.clips.map(normalizeClip),
  };
  const resolvedProduct = {
    ...spec.product,
    beats: spec.product.beats.map((b) => ({
      ...b,
      asset: rewriteAssetPath(b.asset),
      start_seconds: b.start_seconds ?? 0,
    })),
  };

  return {
    ...spec,
    // Cast: at runtime scene.clips is now ResolvedClipRef[] but the
    // declared type union still allows strings. Consumers use the
    // applied-spec type below.
    scene: resolvedScene as unknown as ProgramSpec["scene"],
    product: resolvedProduct as unknown as ProgramSpec["product"],
  };
}

/** Helper for components that consume an applied (post-rewrite) spec. */
export function asResolvedClip(c: ProgramSpec["scene"]["clips"][number]): ResolvedClipRef {
  if (typeof c === "string") return { asset: c, start_seconds: 0 };
  return {
    asset: c.asset,
    start_seconds: c.start_seconds ?? 0,
    duration_seconds: c.duration_seconds,
  };
}

/**
 * Compute final per-clip durations for a section: explicit durations
 * are honored; remaining clips split the remaining time equally.
 */
export function distributeClipDurations(
  clips: ResolvedClipRef[],
  totalSeconds: number
): number[] {
  const explicit = clips.map((c) => c.duration_seconds);
  const setSum = explicit.reduce<number>((acc, d) => acc + (d ?? 0), 0);
  const unsetCount = explicit.filter((d) => d == null).length;
  const remaining = Math.max(0, totalSeconds - setSum);
  const each = unsetCount > 0 ? remaining / unsetCount : 0;
  return explicit.map((d) => d ?? each);
}

export function parseProgramSpec(yamlText: string): ProgramSpec {
  const parsed = parse(yamlText);
  const result = ProgramSpecSchema.safeParse(parsed);
  if (!result.success) {
    const detail = result.error.issues
      .map((i) => `${i.path.join(".")}: ${i.message}`)
      .join("; ");
    throw new ProgramSpecError(`Invalid program spec: ${detail}`, result.error.issues);
  }
  return result.data;
}
