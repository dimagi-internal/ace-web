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
  // Visually distinguish global / locked content from per-program
  // editable panels (VOICEOVER, stat cards). The lock icon + amber
  // accent + reduced opacity all signal "you can't edit this here;
  // change it in programs/_defaults.yaml instead". Without the
  // signal these cards read as just another editable section.
  return (
    <div className="rounded border border-dashed border-amber-700/40 bg-amber-950/5 p-3">
      <div className="mb-1 flex items-center gap-1.5">
        <svg
          aria-hidden
          className="h-3 w-3 text-amber-600/70"
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
        <span className="text-xs font-medium uppercase tracking-wide text-amber-700/80 dark:text-amber-500/80">
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
