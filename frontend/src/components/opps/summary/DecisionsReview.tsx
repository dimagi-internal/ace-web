import { useMemo, useState } from "react";

import type {
  DecisionReaction,
  OppSummaryPayload,
  PublicDecisionEdit,
  ReviewDecision,
} from "@/api/oppSummary";
import { DecisionRow } from "@/components/opps/decisions/DecisionRow";
import { DecisionSection } from "@/components/opps/decisions/DecisionSection";
import { asksConfirmation } from "@/components/opps/decisions/decisionDisplay";
import {
  DecisionItem,
  type DecisionEditSubmit,
} from "@/components/opps/summary/DecisionItem";
import type { ReactionSubmit } from "@/components/opps/summary/DecisionReactions";
import { SignInToEdit } from "@/components/opps/summary/SignInToEdit";
import { cn } from "@/lib/utils";

export type { DecisionEditSubmit };

/**
 * The run's decisions log on the summary — read by anyone, confirmed,
 * changed and discussed by signed-in workspace members.
 *
 * ## One row design, grouped by what the reviewer must DO (2026-10-03)
 *
 * - **Confirm before launch** — pinned on top, open: the rows ACE marks
 *   `review_ask: recommended-confirmation`. They are ordinary decision
 *   rows (Jonathan: "it is the same data model … render those rows with
 *   the SAME row component"), so the shared row draws their marker and
 *   `confirm_reason`; nothing here is a separate card.
 * - **Choices ACE made** — every other live row, by phase.
 * - Hidden by default behind toggles: `audience: internal` rows and
 *   superseded rows (history the run replaced).
 *
 * `evidence_basis: conflicting` is a quiet per-row note, never a headline
 * count. One decision, one home: a pinned row is not repeated below.
 *
 * ## Members write; everyone reads
 *
 * There is no anonymous editing (Jonathan, 2026-10-03). The API refuses
 * a write from anyone but a signed-in workspace member; this page offers
 * "Sign in to edit" to everyone else and renders the same rows read-only.
 */

interface PhaseGroup {
  key: string;
  label: string;
  ordinal: number;
  rows: ReviewDecision[];
}

/**
 * The heading a phase group reads under. Members see the Workbench's
 * phase name; an outside reader sees the plain stage name ("App build")
 * the rest of the page uses, falling back to the phase name when the
 * row carries none.
 */
export function phaseGroupLabel(d: ReviewDecision, plain: boolean): string {
  return (plain && d.stage_label) || d.phase_label;
}

/** A row ACE recommends the reviewer confirm before launch. Live rows only. */
export function isRecommendedConfirmation(d: ReviewDecision): boolean {
  return asksConfirmation(d);
}

/** A row ACE wrote for itself, not the partner. Absent audience = partner. */
export function isInternal(d: ReviewDecision): boolean {
  return d.audience === "internal";
}

/**
 * Has a human acted on a confirm-recommended row — confirmed it, or
 * changed it? A revert back to the AI default with nothing to say is not
 * an answer to the ask.
 */
export function isConfirmationHandled(edit?: PublicDecisionEdit): boolean {
  return !!edit && (!!edit.confirmed || !edit.is_revert);
}

/**
 * The Overview headline's number: how many recommended confirmations are
 * still waiting. One predicate for both surfaces, so the headline and the
 * tab below it can never disagree (the ace-web#771 lesson).
 */
export function confirmationCounts(
  rows: readonly ReviewDecision[],
  edits: Record<string, PublicDecisionEdit>,
): { total: number; outstanding: number } {
  const asked = rows.filter(isRecommendedConfirmation);
  return {
    total: asked.length,
    outstanding: asked.filter((d) => !isConfirmationHandled(edits[d.id])).length,
  };
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
  /** A signed-in member of this workspace — the only viewer who may write. */
  viewerIsMember: boolean;
  onReact: (decisionId: string, body: ReactionSubmit) => Promise<void>;
  onEdit: (decisionId: string, body: DecisionEditSubmit) => Promise<void>;
}) {
  const [showInternal, setShowInternal] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const { counts, rows, total } = decisions;

  const toConfirm = useMemo(() => rows.filter(isRecommendedConfirmation), [rows]);
  const confirmIds = useMemo(() => new Set(toConfirm.map((d) => d.id)), [toConfirm]);
  const rest = useMemo(() => rows.filter((d) => !confirmIds.has(d.id)), [rows, confirmIds]);
  const internalCount = rest.filter((d) => !d.superseded_by && isInternal(d)).length;
  const historyCount = rest.filter((d) => !!d.superseded_by).length;
  const visible = useMemo(
    () =>
      rest.filter(
        (d) =>
          (showHistory || !d.superseded_by) && (showInternal || !isInternal(d)),
      ),
    [rest, showHistory, showInternal],
  );

  const changed = rows.filter(
    (d) => !d.superseded_by && edits[d.id] && !edits[d.id].is_revert && !edits[d.id].confirmed,
  ).length;
  const confirmedCount = rows.filter((d) => !d.superseded_by && edits[d.id]?.confirmed).length;
  const { outstanding } = confirmationCounts(rows, edits);

  const groups = useMemo<PhaseGroup[]>(() => {
    const byPhase = new Map<string, PhaseGroup>();
    for (const d of visible) {
      const key = d.phase_raw || d.phase;
      const g = byPhase.get(key);
      if (g) g.rows.push(d);
      else
        byPhase.set(key, {
          key,
          label: phaseGroupLabel(d, !viewerIsMember),
          ordinal: d.phase_ordinal,
          rows: [d],
        });
    }
    return [...byPhase.values()].sort((a, b) => a.ordinal - b.ordinal);
  }, [visible, viewerIsMember]);

  // Phases start OPEN: a collapsed row says what was decided in full, so
  // the open list is the scannable summary; a phase is collapsed by choice.
  const [closedPhases, setClosedPhases] = useState<Record<string, boolean>>({});
  const [pinnedOpen, setPinnedOpen] = useState(true);
  const [openRows, setOpenRows] = useState<Record<string, boolean>>({});
  const allOpen = groups.every((g) => !closedPhases[g.key]);
  const toggleRow = (id: string) =>
    setOpenRows((prev) => ({ ...prev, [id]: !prev[id] }));

  function toggleAll() {
    setClosedPhases(
      allOpen ? Object.fromEntries(groups.map((g) => [g.key, true])) : {},
    );
  }

  const item = (d: ReviewDecision) => (
    <DecisionItem
      decision={d}
      open={!!openRows[d.id]}
      onToggle={() => toggleRow(d.id)}
      reactions={reactions[d.id] ?? []}
      edit={edits[d.id]}
      canWrite={viewerIsMember}
      onReact={onReact}
      onEdit={onEdit}
      tags={isInternal(d) ? <InternalTag /> : undefined}
    />
  );

  return (
    <div>
      <p className="max-w-3xl text-[0.975rem] leading-[1.7] text-muted-foreground">
        ACE made <span className="text-foreground">{total}</span> load-bearing calls building
        this run. Each one records what it picked, what else was on the table, and why.{" "}
        {viewerIsMember ? (
          <>
            <span className="text-foreground">You can confirm or change any of them here</span>
            {" "}— what you change is what the next run builds from.
          </>
        ) : (
          <>Members of this workspace can confirm or change them.</>
        )}
      </p>

      {!viewerIsMember && (
        <div className="mt-3">
          <SignInToEdit>Sign in to confirm, change or comment</SignInToEdit>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        <Count n={counts.stated} label="stated in a source" />
        <Count n={counts.inferred} label="inferred beyond it" />
        {/* Shown so the numbers add up to the total — neutral, not a call
            to action: that ACE's sources disagreed is ACE's uncertainty. */}
        {counts.conflicting > 0 && (
          <Count n={counts.conflicting} label="where sources disagreed" />
        )}
        <Count n={counts.overridden + changed} label="changed by a human" tone="sky" />
        {confirmedCount > 0 && <Count n={confirmedCount} label="confirmed" tone="emerald" />}
      </div>

      {toConfirm.length > 0 && (
        <DecisionSection
          open={pinnedOpen}
          onToggle={() => setPinnedOpen((v) => !v)}
          className="mt-8"
          lead={
            <span className="text-sm font-semibold text-foreground">Confirm before launch</span>
          }
          chips={
            <span className="text-xs text-muted-foreground">
              {outstanding === 0
                ? `All ${toConfirm.length} answered`
                : `${outstanding} of ${toConfirm.length} still to confirm`}
            </span>
          }
        >
          {toConfirm.map((d) => (
            <li key={d.id}>{item(d)}</li>
          ))}
        </DecisionSection>
      )}

      <div className="mt-9 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-[11px] font-medium uppercase tracking-[0.16em] text-foreground">
          Choices ACE made
        </h3>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          {internalCount > 0 && (
            <ToggleChip pressed={showInternal} onClick={() => setShowInternal((v) => !v)}>
              {showInternal ? "Hide" : "Show"} {internalCount} internal
            </ToggleChip>
          )}
          {historyCount > 0 && (
            <ToggleChip pressed={showHistory} onClick={() => setShowHistory((v) => !v)}>
              {showHistory ? "Hide" : "Show"} {historyCount} replaced
            </ToggleChip>
          )}
          {groups.length > 0 && (
            <button
              type="button"
              onClick={toggleAll}
              className="font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
            >
              {allOpen ? "Collapse all" : "Expand all"}
            </button>
          )}
        </div>
      </div>

      <div className="mt-1">
        {groups.map((g) => (
          <PhaseSection
            key={g.key}
            group={g}
            showOrdinal={viewerIsMember}
            open={!closedPhases[g.key]}
            onToggle={() =>
              setClosedPhases((prev) => ({ ...prev, [g.key]: !prev[g.key] }))
            }
            changed={
              g.rows.filter(
                (d) => edits[d.id] && !edits[d.id].is_revert && !edits[d.id].confirmed,
              ).length
            }
          >
            {g.rows.map((d) => (
              <li key={d.id}>
                {d.superseded_by ? (
                  <ReplacedRow
                    decision={d}
                    open={!!openRows[d.id]}
                    onToggle={() => toggleRow(d.id)}
                  />
                ) : (
                  item(d)
                )}
              </li>
            ))}
          </PhaseSection>
        ))}
      </div>
    </div>
  );
}

/**
 * A superseded row — history the run replaced, shown only when the reader
 * asks for it. Read-only: to bring an old answer back, pick it on the live
 * row, which goes through the attributed edit path.
 */
function ReplacedRow({
  decision,
  open,
  onToggle,
}: {
  decision: ReviewDecision;
  open: boolean;
  onToggle: () => void;
}) {
  const value = decision.override || decision.ai_default;
  return (
    <DecisionRow
      decision={decision}
      effectiveValue={value}
      effectiveReason=""
      open={open}
      onToggle={onToggle}
      statusChip={false}
      muted
      badges={
        <span
          className="shrink-0 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[10px] text-muted-foreground"
          title={`Replaced by ${decision.superseded_by}`}
        >
          replaced — no longer in force
        </span>
      }
    />
  );
}

function InternalTag() {
  return (
    <span
      className="shrink-0 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[10px] text-muted-foreground"
      title="ACE recorded this for its own build; it is not something a partner needs to review"
    >
      internal
    </span>
  );
}

function ToggleChip({
  pressed,
  onClick,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        "rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
        pressed
          ? "border-foreground/40 bg-accent/60 text-foreground"
          : "border-border text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

/**
 * One phase's heading + its rows, on the shared `DecisionSection` shell.
 * Leads with the ordinal and name the Workbench's `PhaseTile` shows —
 * the ordinal for members only: "PHASE 3" means nothing to an outsider.
 */
function PhaseSection({
  group,
  showOrdinal,
  open,
  onToggle,
  changed,
  children,
}: {
  group: PhaseGroup;
  showOrdinal: boolean;
  open: boolean;
  onToggle: () => void;
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
          {showOrdinal && group.ordinal < 99 && (
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
  tone?: "sky" | "emerald";
}) {
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span
        className={cn(
          "text-sm font-medium tabular-nums",
          n === 0
            ? "text-muted-foreground/50"
            : tone === "sky"
              ? "text-sky-400"
              : tone === "emerald"
                ? "text-emerald-400"
                : "text-foreground",
        )}
      >
        {n}
      </span>
      <span className={n === 0 ? "text-muted-foreground/50" : undefined}>{label}</span>
    </span>
  );
}
