import { useBeatEditor } from "../BeatEditorContext";

const BRAND_DESCRIPTIONS: Record<string, string> = {
  intro_hook: 'Animated tagline (from brand template).',
  intro_cycle: "Four-step cycle animation: Learn → Deliver → Verify → Pay.",
  intro_handoff: "Brand handoff card — uses program name from spec.yaml.",
  outro_cta: "End card — logo, tagline, 'Request a demo' link.",
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

  // Detect whether this spec overrides any brand field at all. A truthy
  // tagline OR a 4-entry cycle_steps array counts as override; anything
  // else falls through to the global default.
  const specBrand = (effectiveSpec as { brand?: { tagline?: string; cycle_steps?: string[] } }).brand;
  const overridden =
    !!specBrand &&
    (
      (typeof specBrand.tagline === "string" && specBrand.tagline.trim().length > 0) ||
      (Array.isArray(specBrand.cycle_steps) && specBrand.cycle_steps.length === 4
        && specBrand.cycle_steps.every((s) => typeof s === "string" && s.trim().length > 0))
    );

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

  return (
    <button
      type="button"
      onClick={openEditor}
      className={`group w-full rounded border border-dashed ${palette.border} ${palette.bg} p-3 text-left transition-colors hover:border-solid focus:outline-none focus:ring-1 focus:ring-primary`}
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
        <span className="ml-auto text-xs text-muted-foreground transition-colors group-hover:text-foreground">
          ✏ Edit override
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        {BRAND_DESCRIPTIONS[kind] ?? "Brand-template beat — no per-program content."}
      </p>
      <p className="mt-1 text-xs text-muted-foreground/70">
        {overridden
          ? "This program overrides the global default."
          : "Click to set a program-specific override."}
      </p>
    </button>
  );
}
