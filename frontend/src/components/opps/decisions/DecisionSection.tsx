import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * A collapsible group of decision rows — the section chrome shared by the
 * Workbench's per-phase `DecisionsPanel` and the public run summary's
 * phase sections.
 *
 * Both are the same object: a header you click, some chips on the right
 * saying what's inside, and a divided list of `DecisionRow`s. Owning the
 * card, the header button, the chevron and the list here is what keeps
 * the public surface reading as the Workbench rather than as a lookalike
 * (Jonathan, 2026-08-14).
 *
 * `lead` and `chips` are slots rather than typed fields because the two
 * headers legitimately name different things: the Workbench sits inside a
 * phase panel that already says which phase this is, so it leads with a
 * "Decisions" pill; the summary stacks every phase in one column, so it
 * leads with the phase's ordinal and name.
 */
export function DecisionSection({
  lead,
  chips,
  open,
  onToggle,
  className,
  children,
}: {
  /** Left of the header — the Workbench's pill, or the summary's phase name. */
  lead: React.ReactNode;
  /** Right of the header — counts and attention chips. */
  chips?: React.ReactNode;
  open: boolean;
  onToggle: () => void;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("rounded-lg border border-border bg-card/30", className)}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className={cn(
          "flex w-full items-center gap-2.5 px-4 py-2.5 text-left",
          open ? "border-b border-border/70" : "",
        )}
      >
        {lead}
        <span className="ml-auto flex items-center gap-2 text-[11px]">{chips}</span>
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            open ? "rotate-90 text-foreground" : "",
          )}
        />
      </button>
      {open && <ul className="divide-y divide-border/60">{children}</ul>}
    </section>
  );
}
