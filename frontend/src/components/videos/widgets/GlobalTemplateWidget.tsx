import { useState } from "react";
import { useBeatEditor } from "../BeatEditorContext";

// kind → beat-id mapping for the qa-frame URL. The qa-frame PNGs are
// keyed by beat id (hook, cycle, handoff, cta), but the widget's props
// give us the BeatKind (intro_hook, intro_cycle, intro_handoff,
// outro_cta). Map once instead of asking the caller to pass both.
const KIND_TO_BEAT_ID: Record<string, string> = {
  intro_hook: "hook",
  intro_cycle: "cycle",
  intro_handoff: "handoff",
  outro_cta: "cta",
};

// Per-beat metadata: which global-template field(s) it actually consumes,
// what to label it as, and whether the user can override anything on this
// beat at all. Keeping the source-of-truth table inline (one screen,
// one file) — if the renderer adds a new brand field we update both
// here and Root.tsx's resolveBrand().
type GlobalTemplateField = "tagline" | "cycle_steps";

interface BeatDescriptor {
  description: string;
  overridableFields: GlobalTemplateField[];  // empty → informational only, no override
  readOnlyReason?: string;          // shown when overridableFields is empty
}

const BEATS: Record<string, BeatDescriptor> = {
  intro_hook: {
    description: "Animated tagline shown on screen.",
    overridableFields: ["tagline"],
  },
  intro_cycle: {
    description: "Four-step cycle animation: Learn → Deliver → Verify → Pay.",
    overridableFields: ["cycle_steps"],
  },
  // intro_handoff is no longer routed here — BeatList renders
  // <ProgramNameWidget /> for it because the handoff card edits
  // spec.name, not anything in the global template.
  outro_cta: {
    description: "End card — logo, tagline, 'Request a demo' link.",
    overridableFields: ["tagline"],
  },
};

interface Props {
  beatId: string;
  kind: string;
}

/**
 * Per-beat indicator for the text rendered ON the video during a beat —
 * the on-screen layer, distinct from the voiceover narration. The hook /
 * end-card render the animated tagline; the cycle beat renders the four
 * step labels.
 *
 * Two visual states:
 *   - ON SCREEN (amber lock): the beat renders the shared brand default
 *     from programs/global_style.yaml > global_template.
 *   - ON SCREEN · CUSTOMIZED (emerald): the spec defines its own
 *     global_template.tagline or global_template.cycle_steps. The
 *     renderer prefers these.
 *
 * The whole widget is clickable — opens the GlobalTemplatePanel drawer
 * scoped to this beat's field, showing the default as a placeholder and
 * letting the user fall back by clearing.
 */
export function GlobalTemplateWidget({ beatId, kind }: Props) {
  const { effectiveSpec, dispatch, workspaceSlug, programSlug, runId } = useBeatEditor();
  // Tracks whether the qa-frame for this beat 404'd so we collapse the
  // thumbnail without flashing a broken-image placeholder. Defaults to
  // false (try to show); flips to true on the first error.
  const [previewMissing, setPreviewMissing] = useState(false);

  const beat: BeatDescriptor = BEATS[kind] ?? {
    description: "Brand-template beat — no per-program content.",
    overridableFields: [],
  };
  const readOnly = beat.overridableFields.length === 0;

  // Per-beat override check: this widget shows "overridden" only when
  // one of the fields IT consumes is overridden. Setting just the
  // tagline shouldn't flip the cycle beat's badge to green, and the
  // handoff beat is read-only so it never shows overridden.
  //
  // Reads `spec.global_template`; falls back to legacy `spec.brand`
  // for any spec that hasn't been migrated to the new key yet.
  const specGlobal = (
    effectiveSpec as {
      global_template?: { tagline?: string; cycle_steps?: string[] };
      brand?: { tagline?: string; cycle_steps?: string[] };
    }
  );
  const overrides = specGlobal.global_template ?? specGlobal.brand;
  const fieldOverridden = (f: GlobalTemplateField): boolean => {
    if (!overrides) return false;
    if (f === "tagline") {
      return typeof overrides.tagline === "string" && overrides.tagline.trim().length > 0;
    }
    return (
      Array.isArray(overrides.cycle_steps) &&
      overrides.cycle_steps.length === 4 &&
      overrides.cycle_steps.every((s) => typeof s === "string" && s.trim().length > 0)
    );
  };
  const overridden = beat.overridableFields.some(fieldOverridden);

  const palette = overridden
    ? {
        border: "border-emerald-700/40",
        bg: "bg-emerald-950/5",
        iconColor: "text-emerald-600/70",
        labelColor: "text-emerald-700/80 dark:text-emerald-500/80",
        label: "On screen · customized",
      }
    : {
        border: "border-amber-700/40",
        bg: "bg-amber-950/5",
        iconColor: "text-amber-600/70",
        labelColor: "text-amber-700/80 dark:text-amber-500/80",
        label: "On screen",
      };

  const openEditor = () =>
    dispatch({
      type: "OPEN_DRAWER",
      target: { kind: "global-template", beatId },
    });

  // Read-only beats render as a styled <div> so they don't look like
  // they invite a click. Editable beats render as a <button> with hover
  // affordance and the "Edit override" hint in the corner.
  const Tag = readOnly ? "div" : "button";
  const interactiveProps = readOnly
    ? {}
    : {
        type: "button" as const,
        onClick: openEditor,
      };

  const previewBeatId = KIND_TO_BEAT_ID[kind];
  // Prefix-aware URL — same shape as FinalVideoPlayer / explorer iframe.
  // BASE_URL is `/ace` in prod (path-tenanted ALB) and `/` locally.
  const apiPrefix = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const previewSrc = previewBeatId
    ? `${apiPrefix}/api/w/${workspaceSlug}/videos/programs/${programSlug}/runs/${runId}/qa-frame/${previewBeatId}`
    : null;
  const showPreview = previewSrc && !previewMissing;

  return (
    <Tag
      {...interactiveProps}
      className={`group flex w-full gap-3 rounded border border-dashed ${palette.border} ${palette.bg} p-3 text-left ${readOnly ? "" : "transition-colors hover:border-solid focus:outline-none focus:ring-1 focus:ring-primary"}`}
    >
      {/* QA-frame preview: a still from the rendered video at this
          beat's midpoint. Backend writes it after each render to
          programs/<slug>/runs/<run>/qa-frames/<beat>.png. Falls back
          gracefully (preview hides, layout collapses) when:
            - the run hasn't been rendered yet (404),
            - the beat doesn't have a qa-frame (e.g. unknown kind),
            - the image fails to decode.
          Aspect ratio matches the rendered video (16:9) so the
          thumbnail reads as a video still, not an arbitrary image. */}
      {showPreview && (
        <div className="flex-shrink-0">
          <img
            src={previewSrc}
            alt=""
            loading="lazy"
            decoding="async"
            onError={() => setPreviewMissing(true)}
            className="aspect-video w-28 rounded border border-border/40 bg-muted object-cover"
          />
        </div>
      )}
      <div className="min-w-0 flex-1">
      <div className="mb-1 flex items-center gap-1.5">
        {overridden ? (
          <svg
            aria-hidden
            className={`h-3 w-3 ${palette.iconColor}`}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 20h9" />
            <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
          </svg>
        ) : (
          <svg
            aria-hidden
            className={`h-3 w-3 ${palette.iconColor}`}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
        )}
        <span
          className={`text-xs font-medium uppercase tracking-wide ${palette.labelColor}`}
        >
          {palette.label}
        </span>
        {!readOnly && (
          <span className="ml-auto text-xs text-muted-foreground transition-colors group-hover:text-foreground">
            ✏ Edit
          </span>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        {beat.description}
      </p>
      <p className="mt-1 text-xs text-muted-foreground/70">
        {readOnly
          ? beat.readOnlyReason ?? "Not editable on this beat."
          : overridden
            ? "Customized for this program. Click to edit."
            : "Click to edit the on-screen text."}
      </p>
      </div>
    </Tag>
  );
}
