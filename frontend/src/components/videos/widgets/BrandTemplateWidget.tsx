const BRAND_DESCRIPTIONS: Record<string, string> = {
  intro_hook: 'Animated tagline: "Pay for verified service delivery, not planned activity."',
  intro_cycle: "Four-step cycle animation: Learn → Deliver → Verify → Pay.",
  intro_handoff: "Brand handoff card — uses program name from spec.yaml.",
  outro_cta: "End card — logo, tagline, 'Request a demo' link.",
};

interface Props {
  beatId: string;
  kind: string;
}

export function BrandTemplateWidget({ kind }: Props) {
  return (
    <div className="rounded border border-dashed bg-muted/10 p-3">
      <div className="mb-1 flex items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Brand template · global
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        {BRAND_DESCRIPTIONS[kind] ?? "Brand-template beat — no per-program content."}
      </p>
      <button
        type="button"
        disabled
        title="Brand strings live in programs/_defaults.yaml. Per-program override coming later."
        className="mt-2 cursor-not-allowed text-xs text-muted-foreground underline opacity-60"
      >
        Edit globally
      </button>
    </div>
  );
}
