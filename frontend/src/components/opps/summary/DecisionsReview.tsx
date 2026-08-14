import { useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";

import type {
  DecisionReaction,
  OppSummaryPayload,
  PublicDecisionEdit,
  ReviewDecision,
} from "@/api/oppSummary";
import { DecisionSection } from "@/components/opps/decisions/DecisionSection";
import { ReviewerIdentityFields } from "@/components/opps/decisions/ReviewerIdentityFields";
import {
  MIN_NAME_CHARS,
  rememberIdentity,
  rememberedIdentity,
  type ReviewerIdentity,
} from "@/components/opps/decisions/reviewerIdentity";
import {
  DecisionItem,
  type DecisionEditSubmit,
} from "@/components/opps/summary/DecisionItem";
import type { ReactionSubmit } from "@/components/opps/summary/DecisionReactions";
import { cn } from "@/lib/utils";

export type { DecisionEditSubmit };

/**
 * The public face of the run's decisions log — read, change, or discuss.
 *
 * A 24-page PDD is a bad instrument for eliciting decisions: people skim
 * prose and agree with all of it. Every load-bearing default is already a
 * typed row, so this renders those rows and gets a partner engaging with
 * specific calls. They are **editable in place by anyone with the link**,
 * through the Workbench's own editor into the Workbench's own store.
 *
 * ## Phase IS the structure, the same as the Workbench
 *
 * The Workbench organises decisions by phase, because "which part of the
 * flow produced this call" is how someone reasons about a decision. This
 * surface used to group by phase only INSIDE a collapsed "Show all 42"
 * disclosure, and lift the 2 conflicting rows out of phase context to
 * lead the page — so a reader could not see where a decision arose until
 * they expanded everything, which is exactly backwards (Jonathan,
 * 2026-08-14).
 *
 * Now the phase sections are the page, and the rows inside them are the
 * shared `DecisionRow` the Workbench renders. What the old
 * lead-with-the-conflicts view was PROTECTING is kept without sacrificing
 * the structure:
 *
 * - a phase holding a row that needs an eye opens by default, and those
 *   rows open inside it — so the contested rows are on screen at first
 *   paint, in their phase, not lifted out of it;
 * - the rest collapse to one line each, so 40 routine rows can't bury
 *   them;
 * - "Worth your eye first" is a JUMP LIST, not a second rendering of the
 *   same rows — one decision, one home.
 *
 * The one structural difference from the Workbench is forced: the
 * Workbench is a master/detail layout with a phase rail, and this is a
 * single-column document, so the phases stack as collapsible sections
 * instead of being selected from a sidebar.
 *
 * Editing and commenting are different acts and each row carries both —
 * an edit asserts a value the next run builds from, a comment is
 * discussion that lands in the feedback ledger. Rationale for all of it:
 * `docs/learnings/public-summary-editing.md`.
 */

interface PhaseGroup {
  key: string;
  label: string;
  ordinal: number;
  rows: ReviewDecision[];
}

/** Rows a reader is best placed to correct — contested, or already changed. */
function isFlagged(d: ReviewDecision, edit?: PublicDecisionEdit): boolean {
  return (
    d.evidence_basis === "conflicting" ||
    d.status === "overridden" ||
    (!!edit && !edit.is_revert)
  );
}

export function DecisionsReview({
  decisions,
  reactions,
  edits,
  viewerIsMember,
  onReact,
  onEdit,
}: {
  decisions: NonNullable<OppSummaryPayload["decisions"]>;
  /** Reactions already collected, keyed by decision id. */
  reactions: Record<string, DecisionReaction[]>;
  /** Human-set answers, keyed by decision id. */
  edits: Record<string, PublicDecisionEdit>;
  /** Signed-in viewers are never asked to type a name. */
  viewerIsMember: boolean;
  onReact: (decisionId: string, body: ReactionSubmit) => Promise<void>;
  onEdit: (decisionId: string, body: DecisionEditSubmit) => Promise<void>;
}) {
  const [identity, setIdentity] = useState<ReviewerIdentity>(() =>
    rememberedIdentity(),
  );
  const [editingIdentity, setEditingIdentity] = useState(false);
  // The name we have actually RECORDED, which is not the same as what is
  // half-typed in the identity field right now. Promoting on keystroke
  // would flip a row from confirm to immediate mid-draft and pull the
  // Save button out from under the person filling it in.
  const [knownName, setKnownName] = useState(
    () => rememberedIdentity().name.trim(),
  );
  const { counts, rows, total } = decisions;

  // A signed-in member is resolved server-side; an anonymous reviewer is
  // known once they've successfully submitted something under a name —
  // this visit or a previous one (`reviewerIdentity` remembers it
  // locally). From that point editing is click-and-done, as it is in the
  // Workbench; before it, one confirm step collects the name.
  const identityKnown = viewerIsMember || knownName.length >= MIN_NAME_CHARS;
  // What can be submitted right now, including a name mid-typing.
  const canSubmit =
    viewerIsMember || identity.name.trim().length >= MIN_NAME_CHARS;

  /** A successful write is what establishes who is editing. */
  async function submitEdit(decisionId: string, body: DecisionEditSubmit) {
    await onEdit(decisionId, body);
    if (!viewerIsMember && body.reviewer) setKnownName(body.reviewer.trim());
  }

  async function submitReaction(decisionId: string, body: ReactionSubmit) {
    await onReact(decisionId, body);
    if (!viewerIsMember && body.reviewer) setKnownName(body.reviewer.trim());
  }

  const flagged = useMemo(
    () => rows.filter((d) => isFlagged(d, edits[d.id])),
    [rows, edits],
  );
  const flaggedIds = useMemo(
    () => new Set(flagged.map((d) => d.id)),
    [flagged],
  );
  const changed = useMemo(
    () => rows.filter((d) => edits[d.id] && !edits[d.id].is_revert).length,
    [rows, edits],
  );

  const groups = useMemo<PhaseGroup[]>(() => {
    const byPhase = new Map<string, PhaseGroup>();
    for (const d of rows) {
      const key = d.phase_raw || d.phase;
      const g = byPhase.get(key);
      if (g) g.rows.push(d);
      else
        byPhase.set(key, {
          key,
          label: d.phase_label,
          ordinal: d.phase_ordinal,
          rows: [d],
        });
    }
    return [...byPhase.values()].sort((a, b) => a.ordinal - b.ordinal);
  }, [rows]);

  // A phase opens when it holds something worth an eye; the rest collapse
  // to a one-line header, so the structure is legible at a glance and the
  // contested rows aren't buried under the routine ones.
  const [openPhases, setOpenPhases] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      groups
        .filter((g) => g.rows.some((d) => flaggedIds.has(d.id)))
        .map((g) => [g.key, true]),
    ),
  );
  const [openRows, setOpenRows] = useState<Record<string, boolean>>(() =>
    Object.fromEntries([...flaggedIds].map((id) => [id, true])),
  );

  const allOpen = groups.every((g) => openPhases[g.key]);

  function toggleAll() {
    setOpenPhases(
      allOpen ? {} : Object.fromEntries(groups.map((g) => [g.key, true])),
    );
  }

  /** Open a row where it LIVES — in its phase — and scroll to it. */
  function jumpTo(decision: ReviewDecision) {
    const key = decision.phase_raw || decision.phase;
    setOpenPhases((prev) => ({ ...prev, [key]: true }));
    setOpenRows((prev) => ({ ...prev, [decision.id]: true }));
    requestAnimationFrame(() => {
      document
        .getElementById(`decision-${decision.id}`)
        ?.scrollIntoView?.({ behavior: "smooth", block: "center" });
    });
  }

  // The explicit "Not you?" editor IS a deliberate identity change, so it
  // promotes on the spot (and clearing the name puts the confirm step
  // back, which is how someone un-attributes themselves).
  function changeIdentity(next: ReviewerIdentity) {
    setIdentity(next);
    rememberIdentity(next);
    setKnownName(next.name.trim());
  }

  return (
    <div>
      <p className="text-[0.975rem] leading-[1.7] text-muted-foreground">
        ACE made <span className="text-foreground">{total}</span> load-bearing calls building
        this run, grouped below by the phase of the build that produced them. Each one
        records what it picked, what else was on the table, and why — and{" "}
        <span className="text-foreground">you can change any of them here</span>. What you
        change is what the next run builds from.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        <Count n={counts.stated} label="stated in a source" />
        <Count n={counts.inferred} label="inferred beyond it" />
        <Count n={counts.conflicting} label="resolved a conflict" tone="amber" />
        <Count n={counts.overridden + changed} label="changed by a human" tone="sky" />
      </div>

      {/* Who the changes will be credited to. Asked once (at the first
          submit), then shown here rather than re-asked on every row —
          and correctable, because a wrong name is worse than no name. */}
      {!viewerIsMember && identityKnown && (
        <div className="mt-4 text-[13px] leading-[1.6] text-muted-foreground">
          <p>
            Changes and comments are saved as{" "}
            <span className="font-medium text-foreground">{identity.name.trim()}</span>.{" "}
            <button
              type="button"
              onClick={() => setEditingIdentity((v) => !v)}
              className="font-medium text-foreground underline underline-offset-4"
            >
              {editingIdentity ? "Done" : "Not you?"}
            </button>
          </p>
          {editingIdentity && (
            <div className="mt-2 flex max-w-md flex-col gap-1.5">
              <ReviewerIdentityFields
                identity={identity}
                onChange={changeIdentity}
                note="Clear the name to be asked again before the next change."
              />
            </div>
          )}
        </div>
      )}

      {flagged.length > 0 && (
        <div className="mt-7 rounded-lg border border-amber-500/30 bg-amber-500/[0.06] p-4">
          <h3 className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.16em] text-amber-400">
            <AlertTriangle size={13} />
            Worth your eye first
          </h3>
          <p className="mt-1.5 text-sm leading-[1.6] text-muted-foreground">
            Where the source material disagreed with itself and ACE picked a side, or where
            someone has already changed the answer. They're open in their phase below — jump
            straight to one:
          </p>
          <ul className="mt-2.5 flex flex-col gap-1">
            {flagged.map((d) => (
              <li key={d.id}>
                <button
                  type="button"
                  onClick={() => jumpTo(d)}
                  className="group flex w-full items-baseline gap-2 text-left text-sm leading-[1.5] text-muted-foreground hover:text-foreground"
                >
                  <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wider text-amber-400/80">
                    {phaseTag(d)}
                  </span>
                  <span className="flex-1 text-foreground underline-offset-4 group-hover:underline">
                    {d.question}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-7 flex items-center justify-between gap-3">
        <h3 className="text-[11px] font-medium uppercase tracking-[0.16em] text-foreground">
          Every decision, by phase
        </h3>
        <button
          type="button"
          onClick={toggleAll}
          className="text-sm font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          {allOpen ? "Collapse all" : `Expand all ${total}`}
        </button>
      </div>

      <div className="mt-1">
        {groups.map((g) => (
          <PhaseSection
            key={g.key}
            group={g}
            open={!!openPhases[g.key]}
            onToggle={() =>
              setOpenPhases((prev) => ({ ...prev, [g.key]: !prev[g.key] }))
            }
            needsEye={g.rows.filter((d) => flaggedIds.has(d.id)).length}
            changed={
              g.rows.filter((d) => edits[d.id] && !edits[d.id].is_revert).length
            }
          >
            {g.rows.map((d) => (
              <li key={d.id}>
                <DecisionItem
                  decision={d}
                  open={!!openRows[d.id]}
                  onToggle={() =>
                    setOpenRows((prev) => ({ ...prev, [d.id]: !prev[d.id] }))
                  }
                  reactions={reactions[d.id] ?? []}
                  edit={edits[d.id]}
                  identity={identity}
                  setIdentity={setIdentity}
                  viewerIsMember={viewerIsMember}
                  identityKnown={identityKnown}
                  canSubmit={canSubmit}
                  onReact={submitReaction}
                  onEdit={submitEdit}
                />
              </li>
            ))}
          </PhaseSection>
        ))}
      </div>
    </div>
  );
}

/** `Phase 4 · Connect setup`, or just the label when the ordinal is unknown. */
function phaseTag(d: ReviewDecision): string {
  return d.phase_ordinal < 99
    ? `Phase ${d.phase_ordinal} · ${d.phase_label}`
    : d.phase_label;
}

/**
 * One phase's heading + its rows, on the shared `DecisionSection` shell.
 *
 * The Workbench's per-phase panel leads with a "Decisions" pill because
 * it already sits inside a panel naming the phase; this stacks every
 * phase in one column, so it leads with the ordinal and name the
 * Workbench's `PhaseTile` shows. Chips reuse the Workbench's tones: amber
 * is `EvidenceBadge`'s contested, sky is its "N overridden".
 */
function PhaseSection({
  group,
  open,
  onToggle,
  needsEye,
  changed,
  children,
}: {
  group: PhaseGroup;
  open: boolean;
  onToggle: () => void;
  needsEye: number;
  changed: number;
  children: React.ReactNode;
}) {
  return (
    <DecisionSection
      open={open}
      onToggle={onToggle}
      className="mt-3"
      lead={
        <>
          {group.ordinal < 99 && (
            <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Phase {group.ordinal}
            </span>
          )}
          <span className="truncate text-sm font-semibold text-foreground">
            {group.label}
          </span>
        </>
      }
      chips={
        <>
          {needsEye > 0 && (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-amber-400"
              title={`${needsEye} decision${needsEye === 1 ? "" : "s"} worth your eye`}
            >
              {needsEye} {needsEye === 1 ? "needs" : "need"} your eye
            </span>
          )}
          {changed > 0 && (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-sky-400"
              title={`${changed} decision${changed === 1 ? "" : "s"} changed by a human`}
            >
              {changed} changed
            </span>
          )}
          <span className="text-xs font-medium tabular-nums text-foreground">
            {group.rows.length}
          </span>
        </>
      }
    >
      {children}
    </DecisionSection>
  );
}


function Count({
  n,
  label,
  tone,
}: {
  n: number;
  label: string;
  tone?: "amber" | "sky";
}) {
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span
        className={cn(
          "text-sm font-medium tabular-nums",
          n === 0
            ? "text-muted-foreground/50"
            : tone === "amber"
              ? "text-amber-400"
              : tone === "sky"
                ? "text-sky-400"
                : "text-foreground",
        )}
      >
        {n}
      </span>
      <span className={n === 0 ? "text-muted-foreground/50" : undefined}>{label}</span>
    </span>
  );
}
