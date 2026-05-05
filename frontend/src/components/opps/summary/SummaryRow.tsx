import { ArrowUpRight } from "lucide-react";

interface RowLink {
  label: string;
  href: string;
}

interface Props {
  label: string;
  name: React.ReactNode;
  links: RowLink[];
}

/**
 * The repeated unit for every section: a small uppercase label, a
 * primary name, and 1+ deep-link targets on the right. Adjacent rows
 * inside a `<SummarySection>` get a hairline separator.
 *
 * Whole-row hover surfaces a soft background tint so the row reads
 * as a single clickable unit; the actual links remain the affordance.
 * External-deeplink icon (``ArrowUpRight``) signals "you'll leave this
 * page" rather than a generic in-page arrow.
 */
export function SummaryRow({ label, name, links }: Props) {
  return (
    <div className="group flex items-baseline justify-between gap-6 -mx-3 px-3 py-3.5 rounded-md transition-colors [&+&]:border-t [&+&]:border-border hover:bg-muted/40">
      <span className="w-16 shrink-0 text-[11px] uppercase tracking-[0.16em] text-muted-foreground/80 group-hover:text-muted-foreground">
        {label}
      </span>
      <span className="flex-1 text-[0.975rem] text-foreground">{name}</span>
      <span className="flex items-baseline gap-5 whitespace-nowrap text-sm">
        {links.map((l) => (
          <a
            key={l.href + l.label}
            href={l.href}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 font-medium text-foreground decoration-foreground/30 underline-offset-4 transition-all hover:underline hover:decoration-foreground"
          >
            {l.label}
            <ArrowUpRight
              size={14}
              strokeWidth={2}
              className="opacity-60 transition-transform group-hover:translate-x-0.5"
            />
          </a>
        ))}
      </span>
    </div>
  );
}
