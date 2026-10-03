import { useState } from "react";
import { CheckCircle2, ExternalLink, RefreshCw, ShieldAlert, ShieldQuestion } from "lucide-react";

import type { ReleasePlan, ReleasePlanAction, ReleaseReadiness, ReleaseReadinessItem } from "@/api/types.ws";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "canopy-ui/ui";
import { cn } from "@/lib/utils";

/**
 * Is this run ready to share with the partner? The ACE plugin's
 * `validate-release-readiness` makes one final pass
 * across everything the run produced, does every piece of work a release could
 * cause except sharing, and writes a READY / NOT READY verdict. A READY verdict
 * carries the release plan: the exact share actions `/ace:release` will run,
 * and nothing else. The pill sits in the run's tab row, where the release
 * decision is made; clicking it lists what blocks release, or — when ready —
 * exactly what releasing will share.
 *
 * A read-only validation (a dry run) never counts as ready, a READY verdict
 * with no readable plan asks to be re-validated, and a run
 * that was never validated says so rather than looking fine.
 */
export function ReleaseReadinessBadge({ readiness }: { readiness: ReleaseReadiness | null | undefined }) {
  const [open, setOpen] = useState(false);

  if (!readiness) {
    return (
      <span
        className="flex items-center gap-1.5 px-3 text-xs text-muted-foreground/60"
        title="No release-readiness validation has been run on this run — /ace:validate-release-readiness"
      >
        <ShieldQuestion className="h-3 w-3" />
        Not validated
      </span>
    );
  }

  const plan = readiness.release_plan ?? null;
  const readyVerdict = readiness.verdict === "READY" && !readiness.read_only;
  const ready = readyVerdict && plan !== null;
  const needsPlan = readyVerdict && plan === null;
  const label = ready
    ? "Ready to release"
    : needsPlan
      ? "Re-validate"
      : readiness.verdict === "UNREADABLE"
        ? "Readiness unreadable"
        : `Not ready · ${readiness.counts.blockers} blocker${readiness.counts.blockers === 1 ? "" : "s"}`;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "mx-2 my-1.5 flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition-colors",
          ready
            ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20"
            : needsPlan
              ? "border-amber-500/40 bg-amber-500/10 text-amber-500 hover:bg-amber-500/20"
              : "border-rose-500/40 bg-rose-500/10 text-rose-500 hover:bg-rose-500/20",
        )}
        title="Validate release readiness — click for details"
      >
        {ready ? (
          <CheckCircle2 className="h-3 w-3" />
        ) : needsPlan ? (
          <RefreshCw className="h-3 w-3" />
        ) : (
          <ShieldAlert className="h-3 w-3" />
        )}
        {label}
        {readiness.read_only && <span className="text-[10px] opacity-80">(dry run)</span>}
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="flex max-h-[85vh] max-w-3xl flex-col gap-3">
          <DialogHeader>
            <DialogTitle>
              {ready ? "Ready to release" : needsPlan ? "Re-validate before release" : "Not ready to release"}
            </DialogTitle>
            <DialogDescription>
              Release-readiness validation{readiness.checked_at ? ` of ${formatWhen(readiness.checked_at)}` : ""}
              {readiness.read_only ? " — a dry run, which never counts as ready" : ""}.{" "}
              {readiness.counts.blockers} blocker{readiness.counts.blockers === 1 ? "" : "s"},{" "}
              {readiness.counts.warnings} warning{readiness.counts.warnings === 1 ? "" : "s"}.
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            {needsPlan && (
              <p className="mb-4 rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm">
                This verdict carries no readable release plan. /ace:release
                needs a release plan from /ace:validate-release-readiness — run it again on this run.
              </p>
            )}
            {ready && plan && <PlanView plan={plan} />}
            <ItemList title="Blockers — must be fixed before release" items={readiness.blockers} tone="rose" />
            <ItemList title="Warnings — should be fixed" items={readiness.warnings} tone="amber" />
          </div>
          {readiness.report?.url && (
            <a
              href={readiness.report.url}
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

/** Grant-table columns: the systems a reviewer is given (or not given) access in. */
const GRANT_COLUMNS: { system: string; label: string }[] = [
  { system: "hq", label: "HQ" },
  { system: "connect", label: "Connect" },
  { system: "drive", label: "Drive" },
  { system: "ace-web", label: "ace-web" },
  { system: "ocs", label: "OCS" },
];

/** Per-run share actions (not tied to one reviewer): Drive shares and the forward-source link. */
function isRunLevel(a: ReleasePlanAction): boolean {
  return a.kind === "drive_share" || a.kind === "forward_source";
}

function PlanView({ plan }: { plan: ReleasePlan }) {
  const reviewers = plan.reviewers.map((r) => r.email);
  for (const a of plan.actions) {
    if (a.email && !isRunLevel(a) && a.system !== "email" && !reviewers.includes(a.email)) {
      reviewers.push(a.email);
    }
  }
  const roleOf = new Map(plan.reviewers.map((r) => [r.email, r.role]));
  const runLevel = plan.actions.filter(isRunLevel);

  return (
    <section className="mb-4 flex flex-col gap-3">
      <p className="text-sm text-foreground">
        Releasing executes only these share actions — nothing else in the run changes.
      </p>
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Reviewers and access
        </h3>
        {reviewers.length === 0 ? (
          <p className="text-sm text-muted-foreground">No reviewers named.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-muted-foreground">
                  <th className="py-1 pr-3 font-medium">Reviewer</th>
                  {GRANT_COLUMNS.map((c) => (
                    <th key={c.system} className="py-1 pr-3 font-medium">
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {reviewers.map((email) => (
                  <tr key={email} className="border-t border-border/50 align-top">
                    <td className="py-1.5 pr-3">
                      <span className="font-mono [overflow-wrap:anywhere]">{email}</span>
                      {roleOf.get(email) && (
                        <span className="ml-1 text-muted-foreground">({roleOf.get(email)})</span>
                      )}
                    </td>
                    {GRANT_COLUMNS.map((c) => (
                      <td key={c.system} className="py-1.5 pr-3">
                        <GrantCell plan={plan} email={email} system={c.system} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {runLevel.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Shared for the run
          </h3>
          <ul className="flex flex-col gap-1 text-xs">
            {runLevel.map((a, i) => (
              <li key={a.id ?? i}>
                {a.kind === "forward_source" ? (
                  <>
                    Forward the already-shared link{a.target ? <> from <span className="font-mono">{a.target}</span></> : null}
                    {a.cross_workspace ? " (from another workspace)" : ""}
                  </>
                ) : (
                  <>
                    Drive:{" "}
                    {a.url ? (
                      <a href={a.url} target="_blank" rel="noreferrer" className="underline">
                        {a.title || a.target || "file"}
                      </a>
                    ) : (
                      a.title || a.target || "file"
                    )}
                    {a.role ? ` — ${a.role}` : ""}
                    {a.scope === "anyone_with_link" ? ", anyone with the link" : a.scope ? `, ${a.scope}` : ""}
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {plan.emails.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Emails</h3>
          <ul className="flex flex-col gap-2">
            {plan.emails.map((e, i) => (
              <li key={i} className="rounded border border-border/60 px-3 py-2 text-xs">
                <p>
                  <span className="text-muted-foreground">To: </span>
                  <span className="font-mono">{e.to}</span>
                </p>
                <p>
                  <span className="text-muted-foreground">Subject: </span>
                  {e.subject ?? "(no subject)"}
                </p>
                {e.body && (
                  <details className="mt-1">
                    <summary className="cursor-pointer select-none text-muted-foreground">Body</summary>
                    <pre className="mt-1 whitespace-pre-wrap font-sans text-[12px] [overflow-wrap:anywhere]">
                      {e.body}
                    </pre>
                  </details>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function GrantCell({ plan, email, system }: { plan: ReleasePlan; email: string; system: string }) {
  const grants = plan.actions.filter((a) => a.system === system && a.email === email && !isRunLevel(a));
  if (grants.length > 0) {
    return (
      <span className="text-emerald-600 dark:text-emerald-400">
        {grants
          .map((g) => [g.role || "invited", g.shared ? "shared org" : null].filter(Boolean).join(", "))
          .join("; ")}
      </span>
    );
  }
  const refused = plan.not_granted.find((n) => n.system === system && (!n.email || n.email === email));
  if (refused) {
    return <span className="text-muted-foreground">Not granted{refused.reason ? ` — ${refused.reason}` : ""}</span>;
  }
  if (system === "drive" && plan.actions.some((a) => a.kind === "drive_share")) {
    return <span className="text-muted-foreground">By link (below)</span>;
  }
  return <span className="text-muted-foreground/60">—</span>;
}

function ItemList({
  title,
  items,
  tone,
}: {
  title: string;
  items: readonly ReleaseReadinessItem[];
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
