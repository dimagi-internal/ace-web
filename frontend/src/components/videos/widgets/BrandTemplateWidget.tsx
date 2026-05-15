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
      <p className="mt-1 text-xs text-muted-foreground/70">
        Strings live in <code className="rounded bg-muted px-1">programs/_defaults.yaml</code>.
      </p>
    </div>
  );
}
