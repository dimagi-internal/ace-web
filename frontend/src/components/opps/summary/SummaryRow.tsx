import { ArrowRight } from "lucide-react";

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
 */
export function SummaryRow({ label, name, links }: Props) {
  return (
    <div className="flex items-baseline justify-between gap-6 py-3 [&+&]:border-t [&+&]:border-border">
      <span className="w-16 shrink-0 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </span>
      <span className="flex-1 text-[0.975rem] text-foreground">{name}</span>
      <span className="flex items-baseline gap-4 whitespace-nowrap text-sm">
        {links.map((l) => (
          <a
            key={l.href + l.label}
            href={l.href}
            target="_blank"
            rel="noreferrer"
            className="group inline-flex items-center gap-1 text-primary hover:underline"
          >
            {l.label}
            <ArrowRight
              size={14}
              className="transition-transform group-hover:translate-x-0.5"
            />
          </a>
        ))}
      </span>
    </div>
  );
}
