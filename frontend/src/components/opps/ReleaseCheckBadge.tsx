import { useState } from "react";
import { CheckCircle2, ExternalLink, ShieldAlert, ShieldQuestion } from "lucide-react";

import type { ReleaseCheck, ReleaseCheckItem } from "@/api/types.ws";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "canopy-ui/ui";
import { cn } from "@/lib/utils";

/**
 * Is this run ready to share with the partner? The ACE plugin's
 * `release-check` makes one final pass across everything the run produced and
 * writes a READY / NOT READY verdict; `/ace:release` refuses to invite anyone
 * without READY. The pill sits in the run's tab row, where the release
 * decision is made; clicking it lists what blocks release and how to fix it.
 *
 * A read-only check (a dry run) never counts as ready, and a run that was
 * never checked says so rather than looking fine.
 */
export function ReleaseCheckBadge({ check }: { check: ReleaseCheck | null | undefined }) {
  const [open, setOpen] = useState(false);

  if (!check) {
    return (
      <span
        className="flex items-center gap-1.5 px-3 text-xs text-muted-foreground/60"
        title="No release check has been run on this run — /ace:release-check"
      >
        <ShieldQuestion className="h-3 w-3" />
        Not release-checked
      </span>
    );
  }

  const ready = check.verdict === "READY" && !check.read_only;
  const label = ready
    ? "Ready to release"
    : check.verdict === "UNREADABLE"
      ? "Release check unreadable"
      : `Not ready · ${check.counts.blockers} blocker${check.counts.blockers === 1 ? "" : "s"}`;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "mx-2 my-1.5 flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition-colors",
          ready
            ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20"
            : "border-rose-500/40 bg-rose-500/10 text-rose-500 hover:bg-rose-500/20",
        )}
        title="Release check — click for details"
      >
        {ready ? <CheckCircle2 className="h-3 w-3" /> : <ShieldAlert className="h-3 w-3" />}
        {label}
        {check.read_only && <span className="text-[10px] opacity-80">(dry run)</span>}
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="flex max-h-[85vh] max-w-3xl flex-col gap-3">
          <DialogHeader>
            <DialogTitle>{ready ? "Ready to release" : "Not ready to release"}</DialogTitle>
            <DialogDescription>
              Release check{check.checked_at ? ` of ${formatWhen(check.checked_at)}` : ""}
              {check.read_only ? " — a dry run, which never counts as ready" : ""}.{" "}
              {check.counts.blockers} blocker{check.counts.blockers === 1 ? "" : "s"},{" "}
              {check.counts.warnings} warning{check.counts.warnings === 1 ? "" : "s"}.
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            <ItemList title="Blockers — must be fixed before release" items={check.blockers} tone="rose" />
            <ItemList title="Warnings — should be fixed" items={check.warnings} tone="amber" />
          </div>
          {check.report?.url && (
            <a
              href={check.report.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 self-start text-xs text-muted-foreground hover:text-foreground"
            >
              Full report <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

function ItemList({
  title,
  items,
  tone,
}: {
  title: string;
  items: readonly ReleaseCheckItem[];
  tone: "rose" | "amber";
}) {
  if (items.length === 0) return null;
  return (
    <section className="mb-4">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h3>
      <ul className="flex flex-col gap-2">
        {items.map((it, i) => {
          // Lead with ACE's plain sentence and next step when the verdict
          // carries them (2026-10); older verdicts only have the internal
          // `detail` / `fix`, which then lead instead. Skill ids and area
          // chips are reference, so they sit on a small muted line, and the
          // internal text stays reachable rather than being dropped.
          const lead = it.summary || it.detail;
          const next = it.action || it.fix;
          const technical = [
            it.summary && it.detail ? it.detail : null,
            it.action && it.fix ? `Fix: ${it.fix}` : null,
          ].filter(Boolean) as string[];
          return (
            <li
              key={it.id ?? i}
              className={cn(
                "rounded border px-3 py-2 text-sm",
                tone === "rose" ? "border-rose-500/30 bg-rose-500/5" : "border-amber-500/30 bg-amber-500/5",
              )}
            >
              {lead && <p className="leading-snug text-foreground">{lead}</p>}
              {next && (
                <p className="mt-1 text-[13px] leading-snug text-muted-foreground">
                  <span className="font-medium text-foreground">Next step: </span>
                  {next}
                </p>
              )}
              {(it.area || it.owner) && (
                <p className="mt-1.5 flex flex-wrap items-baseline gap-x-2 text-[10px] text-muted-foreground/70">
                  {it.area && <span className="uppercase tracking-wider">{it.area}</span>}
                  {it.owner && <span className="font-mono">{it.owner}</span>}
                </p>
              )}
              {technical.length > 0 && (
                <details className="mt-1 text-[11px] text-muted-foreground/70">
                  <summary className="cursor-pointer select-none">Technical detail</summary>
                  {technical.map((t, j) => (
                    <p key={j} className="mt-0.5 font-mono [overflow-wrap:anywhere]">
                      {t}
                    </p>
                  ))}
                </details>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}
