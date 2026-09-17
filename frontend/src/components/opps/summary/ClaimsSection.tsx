import { AlertTriangle, Check, CircleHelp, Clock, X } from "lucide-react";

import type { OppSummaryPayload } from "@/api/oppSummary";

type Claims = NonNullable<OppSummaryPayload["claims"]>;
type Claim = Claims["people"][number]["claims"][number];

/**
 * "What changed because you asked" — the run's claim set.
 *
 * A CLAIM is a falsifiable statement about what THIS run's output had to
 * look like, written because a named person decided something between
 * runs. The design puts this section on two surfaces — this page and the
 * reply — and it lives at the top because it answers a returning
 * reviewer's FIRST question: did the thing I asked for happen.
 *
 * Three renderings carry the design's weight and are not decoration.
 * Every one of them is asserted in `ClaimsSection.test.tsx`:
 *
 * 1. **Every claim renders whichever way it went.** The claim set is the
 *    DENOMINATOR, so an unmet claim appears as an accusation rather than
 *    as an absence. Nothing filters, nothing collapses, and the tally
 *    leads so a reader knows the shape before the detail. It is the same
 *    completeness property that makes `UNROUTED` work in the feedback
 *    ledger.
 * 2. **A claim the counterpart authored is marked as theirs.** ACE writes
 *    its own exam here, and the design's only mitigation is that the
 *    reviewer can see which bar was hers — and say so when ACE's is too
 *    low. Drop the marking and the mitigation goes with it.
 * 3. **A `judged` verdict is qualified.** It reads as weaker than a
 *    probed one rather than borrowing its authority.
 *
 * Matches `lib/render-claims.ts::renderClaimsSection` in the ACE plugin
 * rather than inventing a second contract (ace#2420).
 */

const VERDICT: Record<
  string,
  { label: string; icon: typeof Check; className: string }
> = {
  MET: { label: "Met", icon: Check, className: "text-emerald-400" },
  UNMET: { label: "Not met", icon: X, className: "text-red-400" },
  "NOT REACHED": {
    label: "Never reached",
    icon: AlertTriangle,
    className: "text-amber-400",
  },
  INDETERMINATE: {
    label: "Indeterminate",
    icon: CircleHelp,
    className: "text-amber-400",
  },
};

//: No verdict yet. NEVER folded into "met" — a claim nobody answered is a
//: claim nobody answered, and rendering it as anything else is the exact
//: silence this section exists to remove.
const STILL_OPEN = {
  label: "Still open",
  icon: Clock,
  className: "text-muted-foreground",
};

function ClaimRow({ claim }: { claim: Claim }) {
  const v = (claim.verdict && VERDICT[claim.verdict]) || STILL_OPEN;
  const Icon = v.icon;
  return (
    <li className="flex gap-3 py-3.5 [&+&]:border-t [&+&]:border-border">
      <Icon
        size={15}
        strokeWidth={2.5}
        aria-hidden
        className={`mt-1 shrink-0 ${v.className}`}
      />
      <div className="min-w-0">
        <p className="text-[0.975rem] leading-[1.6] text-foreground">
          <span className={`font-medium ${v.className}`}>{v.label}</span>
          {claim.evidence_kind === "judged" && (
            <span className="text-muted-foreground"> (judged, not probed)</span>
          )}
          {" — "}
          {claim.claim}
          {claim.authored_by === "counterpart" && (
            <span className="ml-1.5 whitespace-nowrap rounded border border-border px-1.5 py-0.5 align-[1px] text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              you asked for this one
            </span>
          )}
        </p>
        {/* The counterpart-facing sentence. Its absence renders as
            silence, never as the audit `evidence` in its place — that
            field is Drive ids and MCP atom signatures (ace#2386). */}
        {claim.says && (
          <p className="mt-1 text-[0.9rem] leading-[1.6] text-muted-foreground">
            {claim.says}
          </p>
        )}
        {claim.would_settle_it && (
          <p className="mt-1 text-[0.9rem] leading-[1.6] text-muted-foreground">
            What would settle it: {claim.would_settle_it}
          </p>
        )}
        {/* Members only — served as `null` to everyone else, so this is
            never the reason a claim looks different to two readers. */}
        {claim.evidence && (
          <details className="mt-1.5">
            <summary className="cursor-pointer text-[0.8rem] text-muted-foreground/70 underline-offset-4 hover:underline">
              How we checked
            </summary>
            <p className="mt-1 whitespace-pre-wrap text-[0.85rem] leading-[1.6] text-muted-foreground/80">
              {claim.evidence}
            </p>
          </details>
        )}
      </div>
    </li>
  );
}

export function ClaimsSection({ claims }: { claims: Claims }) {
  return (
    <div>
      <p className="text-[0.975rem] leading-[1.7] text-muted-foreground">
        <span className="text-foreground">{claims.summary}</span>
        {claims.total > 0 &&
          " — every decision made between runs, and whether this run acted on it."}
      </p>

      {/* An unreadable claims file is a VISIBLE problem. Silence here
          would put the reader back in front of a page that renders an
          omission as an absence. */}
      {claims.error && (
        <p className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/[0.06] p-3 text-[0.9rem] leading-[1.6] text-amber-200">
          {claims.error}
        </p>
      )}

      {claims.people.map((group) => (
        <div key={group.person} className="mt-4">
          {claims.people.length > 1 && (
            <h3 className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground/60">
              {group.person}
            </h3>
          )}
          <ul>
            {group.claims.map((c) => (
              <ClaimRow key={c.id} claim={c} />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
