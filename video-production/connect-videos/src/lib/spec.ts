import { parse } from "yaml";
import { z } from "zod";
import { BeatKind } from "./beats";

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
  // When true the renderer plays the asset as a real video clip
  // (no Ken Burns still-zoom). Used for micro-demo walkthrough clips.
  is_demo_clip: z.boolean().default(false),
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
 *   library:<media>/…       — stable workspace media-library ref. Resolved
 *                              to gdrive:<id>.<ext> server-side by the
 *                              render-prep staging step (apps/videos
 *                              service._stage_spec) BEFORE the renderer runs,
 *                              so the bundle never sees a library: ref.
 *                              applyManifestRefs throws if one reaches it —
 *                              a spec rendered without staging fails loud
 *                              instead of emitting a broken asset path.
 * The rest of the spec references entries with `@<alias>`.
 */
const ManifestEntrySchema = z.string().min(1);

const NarrationVariantSchema = z.object({
  angle_id: z.string().min(1),
  description: z.string().min(1).optional(),
  by_beat: z.record(z.string(), z.string()),
});

// A walkthrough beat (connect-ddd-walkthrough template) plays a RANGE of one
// master clip full-bleed and overlays a single lower-third. The clip
// range reuses the same start_seconds / duration_seconds shape as a
// ClipRef (the range INTO the master clip). The beat's VO rides on
// narration.by_beat[<beatId>]. Keyed by beat id, parallel to
// narration.by_beat — works for any beat id the walkthrough's `beats:`
// list declares. Additive: marketing + connect-explainer specs never
// carry a `walkthrough:` block, so this is inert for them.
const WalkthroughBeatSchema = z.object({
  asset: z.string().min(1),
  start_seconds: z.number().nonnegative().default(0),
  duration_seconds: z.number().positive().optional(),
  // Optional: omit (or leave empty) for a clean full-bleed walkthrough with no
  // lower-third pill — the recorded dashboard usually self-labels and the VO
  // narrates, so the pill is opt-in.
  lower_third: z.string().optional().default(""),
});
export type WalkthroughBeat = z.infer<typeof WalkthroughBeatSchema>;

const ProspectSchema = z.object({
  name: z.string().min(1),
  logo_asset: z.string().min(1).optional(),
  region: z.string().min(1).optional(),
  sector: z.string().min(1).optional(),
});

/**
 * The "how the program is built" beat (program-designer AI cut). Renders
 * a motion-graphic card — no library clip needed — showing the program
 * being assembled into its Connect components. Present + `active_cut: "ai"`
 * renders the body_ai_build beat; drop the block (or flip to the standard
 * cut) and the beat disappears (beats.ts::filterDefaultsForSpec). The
 * per-beat narration is authored in narration.by_beat.ai_build.
 */
const AiBuildSchema = z.object({
  // Card headline, e.g. "AI builds your program — in days, not months".
  headline: z.string().min(1),
  // The Connect components the program is decomposed into, shown
  // assembling on the card, e.g. ["Learn app", "Deliver app",
  // "Verification rules", "Payment logic"]. 2–6 keeps the card legible.
  components: z.array(z.string().min(1)).min(2).max(6),
  // Optional one-line sub-headline under the components.
  subhead: z.string().min(1).optional(),
});

export const ProgramSpecSchema = z.object({
  slug: z.string().regex(/^[a-z0-9-]+$/),
  name: z.string().min(1),
  country_focus: z.string().min(1),
  status: z.string().min(1),
  tagline: z.string().min(1),
  program_url: z.string().url(),
  // Optional prospect identity for partnership-pitch videos. Absent =
  // unbranded "how Connect works" explainer (Dimagi chrome only).
  prospect: ProspectSchema.optional(),
  // Which cut of the video to render. "ai" includes the body_ai_build beat
  // (the "AI builds your program" card); anything else (incl. absent) drops
  // it. Optional + absent-means-standard keeps every spec authored before
  // this field — and every other template — rendering exactly as before
  // (filterDefaultsForSpec only includes the beat on an explicit "ai").
  // One program-designer spec carries the ai_build content and flips
  // this field to switch cuts.
  active_cut: z.enum(["ai", "standard"]).optional(),
  // Optional AI-build beat content (program-designer). Only renders in
  // the AI cut (active_cut: "ai"); see beats.ts::filterDefaultsForSpec.
  ai_build: AiBuildSchema.optional(),
  // The spec's OWN beat timeline (structure-belongs-to-the-template). When
  // present it's authoritative (used verbatim by effectiveBeatsForSpec, no
  // optional-beat filtering); when absent the spec inherits the global
  // programs/global_style.yaml timeline. Optional for back-compat — every
  // pre-existing program spec omits it.
  beats: z
    .array(z.object({ id: z.string(), kind: BeatKind, seconds: z.number().positive() }))
    .optional(),
  beat_overrides: z.record(z.string(), BeatOverrideSchema).optional(),
  manifest: z.record(z.string(), ManifestEntrySchema).optional(),
  // Optional so a walkthrough spec (connect-ddd-walkthrough template) — which
  // carries `beats:` + `walkthrough:` instead of the marketing body — can
  // omit it. The superRefine below requires it when a body_scene beat is
  // in the effective timeline, so any marketing / connect-explainer spec
  // that uses the scene beat still fails loud if it drops this block.
  scene: z
    .object({
      clips: z.array(ClipRefSchema).min(1).max(6),
      lower_third: z.string().min(1),
    })
    .optional(),
  // Optional in "explainer mode": a generic "how Connect works" video
  // omits the problem + impact stat-card beats entirely. When absent,
  // Root.tsx::filterDefaultsForSpec drops the matching beat from the
  // timeline so nothing tries to render a missing field. Specs that
  // include them still validate unchanged (backward compatible).
  problem: StatSchema.optional(),
  // Optional for the same reason as `scene` above — required by the
  // superRefine only when a body_product_beats beat is in the timeline.
  product: z
    .object({
      beats: z.array(ProductBeatSchema).min(1).max(4),
    })
    .optional(),
  impact: z.array(StatSchema).min(2).max(3).optional(),
  // Per-walkthrough-beat clip range + lower-third, keyed by beat id
  // (connect-ddd-walkthrough template). Required (per beat) for every
  // body_walkthrough beat in `beats:` — enforced by the superRefine
  // below. Absent for marketing + connect-explainer specs.
  walkthrough: z.record(z.string(), WalkthroughBeatSchema).optional(),
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
    // Multi-angle narration: each variant is one narrative angle's
    // per-beat text. active_angle selects which variant renders.
    // Legacy specs with only by_beat continue to work unchanged.
    variants: z.array(NarrationVariantSchema).optional(),
    active_angle: z.string().min(1).optional(),
  }).refine(
    (n) => !n.active_angle || (n.variants?.some((v) => v.angle_id === n.active_angle) ?? false),
    { message: "narration.active_angle must match a variants[].angle_id", path: ["active_angle"] },
  ).refine(
    (n) => !(n.variants && n.variants.length > 0) || !!n.active_angle,
    { message: "narration.active_angle is required when variants are present", path: ["active_angle"] },
  ),
  voice: z.object({
    provider: z.enum(["elevenlabs", "none"]),
    voice_id: z.string().min(1),
    model: z.string().min(1),
  }),
}).superRefine((spec, ctx) => {
  // Determine the effective timeline kinds. When `beats:` is supplied it
  // IS the arc (effectiveBeatsForSpec uses it verbatim); otherwise the
  // spec rides the shared global_style.yaml marketing arc, which always
  // includes the body_scene + body_product_beats kinds (problem/impact
  // are filtered out for explainer mode but scene/product are not). So
  // the no-`beats` default below requires scene + product exactly as
  // main did before they became optional — a marketing or
  // connect-explainer spec that drops either still fails loud.
  const kinds = spec.beats?.map((b) => b.kind) ?? ["body_scene", "body_product_beats"];
  const has = (k: string) => kinds.includes(k as (typeof kinds)[number]);

  if (has("body_scene") && !spec.scene)
    ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["scene"], message: "required when a body_scene beat is present" });
  if (has("body_product_beats") && !spec.product)
    ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["product"], message: "required when a body_product_beats beat is present" });

  // Every body_walkthrough beat must have a matching walkthrough entry
  // (clip range + lower_third).
  for (const b of spec.beats ?? []) {
    if (b.kind !== "body_walkthrough") continue;
    if (!spec.walkthrough?.[b.id])
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["walkthrough", b.id],
        message: `required: body_walkthrough beat "${b.id}" needs a walkthrough entry (asset + lower_third)`,
      });
  }
});

export type ProgramSpec = z.infer<typeof ProgramSpecSchema>;

/**
 * The per-beat narration that should actually render. Prefers the
 * active variant (multi-angle specs); falls back to the legacy single
 * by_beat for older specs; empty object if neither is present.
 *
 * The `variants[0]` branch below is a defensive fallback: for
 * schema-validated specs it is unreachable because a non-empty
 * `variants` array requires `active_angle` to be set (enforced by the
 * second `.refine()` on the narration schema).
 */
export function resolveActiveByBeat(spec: ProgramSpec): Record<string, string> {
  const n = spec.narration;
  if (n.variants && n.variants.length > 0) {
    const active = n.active_angle
      ? n.variants.find((v) => v.angle_id === n.active_angle)
      : n.variants[0];
    if (active) return active.by_beat;
  }
  return n.by_beat ?? {};
}

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
    if (ref.startsWith("library:")) {
      // library: refs are stable workspace media-library pointers. They are
      // rewritten to gdrive:<id>.<ext> server-side by the render-prep staging
      // step (apps/videos service._stage_spec) BEFORE the renderer runs, so a
      // library: ref reaching this pure rewrite means the spec was NOT staged.
      // Fail loud rather than silently passing it through as a broken literal
      // path (the prior behaviour, which masked unstaged renders).
      throw new Error(
        `Manifest entry for "@${alias}" is an unresolved library: ref ("${ref}"). ` +
          `library: refs must be rewritten to gdrive:<id>.<ext> by the render-prep ` +
          `staging step (apps/videos service._stage_spec) before the renderer sees ` +
          `the spec. Render via the videos build flow (which stages the spec) rather ` +
          `than feeding a raw library: spec to applyManifestRefs.`
      );
    }
    return ref; // plain path
  };

  type SceneClip = NonNullable<ProgramSpec["scene"]>["clips"][number];
  const normalizeClip = (c: SceneClip): ResolvedClipRef => {
    if (typeof c === "string") return { asset: rewriteAssetPath(c), start_seconds: 0 };
    return {
      asset: rewriteAssetPath(c.asset),
      start_seconds: c.start_seconds ?? 0,
      duration_seconds: c.duration_seconds,
    };
  };

  // We rebuild scene.clips as an array of normalized objects so the
  // composition can rely on a single shape regardless of YAML form.
  // scene/product are optional (walkthrough specs omit them); leave them
  // undefined rather than touching a missing block.
  const resolvedScene = spec.scene
    ? { ...spec.scene, clips: spec.scene.clips.map(normalizeClip) }
    : undefined;
  const resolvedProduct = spec.product
    ? {
        ...spec.product,
        beats: spec.product.beats.map((b) => ({
          ...b,
          asset: rewriteAssetPath(b.asset),
          start_seconds: b.start_seconds ?? 0,
        })),
      }
    : undefined;

  // Walkthrough clip refs (connect-ddd-walkthrough): rewrite each beat's
  // asset the same way as scene clips. Absent for marketing/explainer.
  const resolvedWalkthrough = spec.walkthrough
    ? Object.fromEntries(
        Object.entries(spec.walkthrough).map(([id, w]) => [
          id,
          { ...w, asset: rewriteAssetPath(w.asset), start_seconds: w.start_seconds ?? 0 },
        ]),
      )
    : undefined;

  // Resolve the prospect logo the same way as clip assets so the
  // ProspectBranding overlay can render it. logo_asset is optional —
  // a prospect with a name but no logo (e.g. a greenfield pitch where
  // we haven't sourced the logo) resolves to name-only branding.
  const resolvedProspect = spec.prospect
    ? {
        ...spec.prospect,
        logo_asset: spec.prospect.logo_asset
          ? rewriteAssetPath(spec.prospect.logo_asset)
          : undefined,
      }
    : undefined;

  return {
    ...spec,
    // Cast: at runtime scene.clips is now ResolvedClipRef[] but the
    // declared type union still allows strings. Consumers use the
    // applied-spec type below.
    scene: resolvedScene as unknown as ProgramSpec["scene"],
    product: resolvedProduct as unknown as ProgramSpec["product"],
    walkthrough: resolvedWalkthrough as unknown as ProgramSpec["walkthrough"],
    prospect: resolvedProspect,
  };
}

/** Helper for components that consume an applied (post-rewrite) spec. */
export function asResolvedClip(c: NonNullable<ProgramSpec["scene"]>["clips"][number]): ResolvedClipRef {
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
