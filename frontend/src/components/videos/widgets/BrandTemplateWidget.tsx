import { useBeatEditor } from "../BeatEditorContext";

// Per-beat metadata: which global-template field(s) it actually consumes,
// what to label it as, and whether the user can override anything on this
// beat at all. Keeping the source-of-truth table inline (one screen,
// one file) — if the renderer adds a new brand field we update both
// here and Root.tsx's resolveBrand().
type BrandField = "tagline" | "cycle_steps";

interface BeatDescriptor {
  description: string;
  overridableFields: BrandField[];  // empty → informational only, no override
  readOnlyReason?: string;          // shown when overridableFields is empty
}

const BEATS: Record<string, BeatDescriptor> = {
  intro_hook: {
    description: "Animated tagline (from global template).",
    overridableFields: ["tagline"],
  },
  intro_cycle: {
    description: "Four-step cycle animation: Learn → Deliver → Verify → Pay.",
    overridableFields: ["cycle_steps"],
  },
  intro_handoff: {
    // The handoff card renders `spec.name` directly — it's not part of
    // the global template's brand section. Render as read-only so users
    // don't open a drawer that can't change anything about this beat.
    description: "Handoff card — uses program name from spec.yaml.",
    overridableFields: [],
    readOnlyReason: "Program name comes from spec.yaml, not the global template.",
  },
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
 * Per-beat indicator for content that ships with the brand template.
 *
 * Two visual states:
 *   - GLOBAL TEMPLATE (amber lock): the beat is using values from
 *     programs/_defaults.yaml > brand. No per-program override.
 *   - PROGRAM OVERRIDE (emerald): the spec defines its own brand.tagline
 *     or brand.cycle_steps. The renderer prefers these.
 *
 * The whole widget is now clickable — opens the BrandTemplatePanel
 * drawer where the user can set or clear the override. The drawer
 * shows the global value as a placeholder and lets the user fall back
 * by clearing.
 */
export function BrandTemplateWidget({ beatId, kind }: Props) {
  const { effectiveSpec, dispatch } = useBeatEditor();

  const beat: BeatDescriptor = BEATS[kind] ?? {
    description: "Brand-template beat — no per-program content.",
    overridableFields: [],
  };
  const readOnly = beat.overridableFields.length === 0;

  // Per-beat override check: this widget shows "overridden" only when
  // one of the fields IT consumes is overridden. Setting just the
  // tagline shouldn't flip the cycle beat's badge to green, and the
  // handoff beat is read-only so it never shows overridden.
  const specBrand = (effectiveSpec as { brand?: { tagline?: string; cycle_steps?: string[] } }).brand;
  const fieldOverridden = (f: BrandField): boolean => {
    if (!specBrand) return false;
    if (f === "tagline") {
      return typeof specBrand.tagline === "string" && specBrand.tagline.trim().length > 0;
    }
    return (
      Array.isArray(specBrand.cycle_steps) &&
      specBrand.cycle_steps.length === 4 &&
      specBrand.cycle_steps.every((s) => typeof s === "string" && s.trim().length > 0)
    );
  };
  const overridden = beat.overridableFields.some(fieldOverridden);

  const palette = overridden
    ? {
        border: "border-emerald-700/40",
        bg: "bg-emerald-950/5",
        iconColor: "text-emerald-600/70",
        labelColor: "text-emerald-700/80 dark:text-emerald-500/80",
        label: "Global template · overridden",
      }
    : {
        border: "border-amber-700/40",
        bg: "bg-amber-950/5",
        iconColor: "text-amber-600/70",
        labelColor: "text-amber-700/80 dark:text-amber-500/80",
        label: "Global template",
      };

  const openEditor = () =>
    dispatch({
      type: "OPEN_DRAWER",
      target: { kind: "brand-template", beatId },
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

  return (
    <Tag
      {...interactiveProps}
      className={`group w-full rounded border border-dashed ${palette.border} ${palette.bg} p-3 text-left ${readOnly ? "" : "transition-colors hover:border-solid focus:outline-none focus:ring-1 focus:ring-primary"}`}
    >
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
            ✏ Edit override
          </span>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        {beat.description}
      </p>
      <p className="mt-1 text-xs text-muted-foreground/70">
        {readOnly
          ? beat.readOnlyReason ?? "Not configurable from the global template."
          : overridden
            ? "This program overrides the global default."
            : "Click to set a program-specific override."}
      </p>
    </Tag>
  );
}
