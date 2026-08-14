import { ArrowUpRight } from "lucide-react";

import type { LinkAccess } from "@/api/oppSummary";

interface RowLink {
  label: string;
  href: string;
  /**
   * Set to `"admin"` when the link needs an account we can't give an
   * external partner. The link is still rendered — it just says so.
   *
   * The page leaves this undefined for a signed-in workspace member, so
   * "should this viewer see tags at all" is decided once, at the top,
   * rather than by every row.
   */
  access?: LinkAccess;
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
      <span className="w-20 shrink-0 text-[11px] uppercase tracking-[0.16em] text-muted-foreground/80 group-hover:text-muted-foreground">
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
        {links.some((l) => l.access === "admin") && <AdminOnlyTag />}
      </span>
    </div>
  );
}

/**
 * Marks a link that needs Dimagi access today.
 *
 * Jonathan, 2026-08-14: "Nothing is 'Dimagi only' at scale for ACE, even
 * if right now it needs to be because of shared tenancy. For now we can
 * show the link but have a tag on it (admin only)." Hiding these links
 * (or letting them 404 silently) told an outside reader the run was
 * thinner than it is; the tag says what's actually true.
 */
export function AdminOnlyTag({ className }: { className?: string }) {
  return (
    <span
      className={
        "shrink-0 rounded border border-border bg-muted/40 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground/70 " +
        (className ?? "")
      }
      title="Needs a Dimagi account today — ask us and we'll walk you through it"
    >
      admin only
    </span>
  );
}
