import { useMemo, useState } from "react";
import { CheckCircle2, ChevronRight } from "lucide-react";

import type {
  DecisionReaction,
  OppSummaryPayload,
  PublicDecisionEdit,
  ReviewDecision,
} from "@/api/oppSummary";
import { DecisionRow } from "@/components/opps/decisions/DecisionRow";
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
 * The public face of the run's decisions log — read, confirm, change, or
 * discuss. Every load-bearing default is a typed row, so this renders
 * those rows and gets a partner engaging with specific calls; they are
 * editable in place by anyone with the link, through the Workbench's own
 * editor into the Workbench's own store
 * (`docs/learnings/public-summary-editing.md`).
 *
 * ## Structure: what the reviewer must DO, then what ACE did (2026-10-03)
 *
 * This page used to lead with "Worth your eye first" / "N need your eye",
 * flagging rows whose `evidence_basis` was `conflicting` or that someone
 * had already changed. Jonathan's review: that surfaces ACE's INTERNAL
 * uncertainty, not what the reviewer has to do. So:
 *
 * 1. **Recommended to confirm before launch** — always open, on top: the
 *    rows ACE marks `review_ask: recommended-confirmation`. Each states
 *    the value the build uses and ACE's plain `confirm_reason`, and offers
 *    **Confirm** (recorded distinctly from a change — `confirm: true` on
 *    the same edit endpoint) or **Change it** (the usual editor).
 * 2. **Choices ACE made** — every other live row, by phase, collapsible.
 *    Phase stays the organising structure, as in the Workbench.
 * 3. Hidden by default behind toggles: `audience: internal` rows and
 *    superseded rows (history the run replaced).
 *
 * `evidence_basis: conflicting` is now a small per-row note ("ACE's
 * sources disagreed") with no headline count and no call to action.
 *
 * One decision, one home: a row in the confirm group is not repeated in
 * its phase below.
 */

interface PhaseGroup {
  key: string;
  label: string;
  ordinal: number;
  rows: ReviewDecision[];
}

/** A row ACE recommends the reviewer confirm before launch. Live rows only. */
export function isRecommendedConfirmation(d: ReviewDecision): boolean {
  return d.review_ask === "recommended-confirmation" && !d.superseded_by;
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
  const [showInternal, setShowInternal] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const { counts, rows, total } = decisions;

  const identityKnown = viewerIsMember || knownName.length >= MIN_NAME_CHARS;
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
          label: d.phase_label,
          ordinal: d.phase_ordinal,
          rows: [d],
        });
    }
    return [...byPhase.values()].sort((a, b) => a.ordinal - b.ordinal);
  }, [visible]);

  // Phases start OPEN: a collapsed row now says what was decided in full,
  // so the open list is the scannable summary; a phase is collapsed by
  // choice, not by default.
  const [closedPhases, setClosedPhases] = useState<Record<string, boolean>>({});
  const [openRows, setOpenRows] = useState<Record<string, boolean>>({});
  const allOpen = groups.every((g) => !closedPhases[g.key]);

  function toggleAll() {
    setClosedPhases(
      allOpen ? Object.fromEntries(groups.map((g) => [g.key, true])) : {},
    );
  }

  // The explicit "Not you?" editor IS a deliberate identity change, so it
  // promotes on the spot (and clearing the name puts the confirm step
  // back, which is how someone un-attributes themselves).
  function changeIdentity(next: ReviewerIdentity) {
    setIdentity(next);
    rememberIdentity(next);
    setKnownName(next.name.trim());
  }

  const itemProps = {
    identity,
    setIdentity,
    viewerIsMember,
    identityKnown,
    canSubmit,
    onReact: submitReaction,
    onEdit: submitEdit,
  };

  return (
    <div>
      <p className="max-w-3xl text-[0.975rem] leading-[1.7] text-muted-foreground">
        ACE made <span className="text-foreground">{total}</span> load-bearing calls building
        this run. Each one records what it picked, what else was on the table, and why — and{" "}
        <span className="text-foreground">you can change any of them here</span>. What you
        change is what the next run builds from.
      </p>

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

      {toConfirm.length > 0 && (
        <section className="mt-8" aria-labelledby="recommended-confirm">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3
              id="recommended-confirm"
              className="text-[11px] font-medium uppercase tracking-[0.16em] text-foreground"
            >
              Recommended to confirm before launch
            </h3>
            <span className="text-xs text-muted-foreground">
              {outstanding === 0
                ? `All ${toConfirm.length} answered`
                : `${outstanding} of ${toConfirm.length} still to confirm`}
            </span>
          </div>
          <p className="mt-1.5 max-w-3xl text-sm leading-[1.6] text-muted-foreground">
            ACE recommends a person confirm these before anyone goes live. Confirm the answer the
            build uses, or change it.
          </p>
          {/* Asked ONCE for the whole group, not on every card. */}
          {!viewerIsMember && !identityKnown && (
            <div className="mt-3 flex max-w-xl flex-col gap-1.5">
              <ReviewerIdentityFields identity={identity} onChange={setIdentity} />
            </div>
          )}
          <ul className="mt-3 grid gap-3 lg:grid-cols-2">
            {toConfirm.map((d) => (
              <ConfirmCard
                key={d.id}
                decision={d}
                edit={edits[d.id]}
                reactions={reactions[d.id] ?? []}
                {...itemProps}
              />
            ))}
          </ul>
        </section>
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
                    onToggle={() =>
                      setOpenRows((prev) => ({ ...prev, [d.id]: !prev[d.id] }))
                    }
                  />
                ) : (
                  <DecisionItem
                    decision={d}
                    open={!!openRows[d.id]}
                    onToggle={() =>
                      setOpenRows((prev) => ({ ...prev, [d.id]: !prev[d.id] }))
                    }
                    reactions={reactions[d.id] ?? []}
                    edit={edits[d.id]}
                    tags={isInternal(d) ? <InternalTag /> : undefined}
                    {...itemProps}
                  />
                )}
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
 * One recommended confirmation: the value in force, why ACE wants a human
 * to confirm it, and the two answers — Confirm, or Change it.
 *
 * Confirm posts the CURRENT value with `confirm: true` through the same
 * edit endpoint a change uses, so it lands in the same store with the same
 * attribution and history, but reads back as "confirmed by <name>" rather
 * than "changed by". Change opens the ordinary row editor in place.
 */
function ConfirmCard({
  decision,
  edit,
  reactions,
  identity,
  setIdentity,
  viewerIsMember,
  identityKnown,
  canSubmit,
  onReact,
  onEdit,
}: {
  decision: ReviewDecision;
  edit?: PublicDecisionEdit;
  reactions: DecisionReaction[];
  identity: ReviewerIdentity;
  setIdentity: (next: ReviewerIdentity) => void;
  viewerIsMember: boolean;
  identityKnown: boolean;
  canSubmit: boolean;
  onReact: (decisionId: string, body: ReactionSubmit) => Promise<void>;
  onEdit: (decisionId: string, body: DecisionEditSubmit) => Promise<void>;
}) {
  const [changing, setChanging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const answer = edit?.override || decision.override || decision.ai_default;
  const confirmed = !!edit?.confirmed;
  const changedBy = edit && !edit.is_revert && !confirmed ? edit.decided_by_name : null;

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await onEdit(decision.id, {
        value: answer,
        confirm: true,
        ...(viewerIsMember
          ? {}
          : {
              reviewer: identity.name.trim(),
              reviewer_email: identity.email.trim() || undefined,
            }),
      });
      if (!viewerIsMember) rememberIdentity(identity);
    } catch (err) {
      setError(err instanceof Error ? err.message : "We couldn't record that confirmation.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li
      id={`decision-${decision.id}`}
      className={cn(
        "flex min-w-0 scroll-mt-24 flex-col rounded-lg border bg-card/40 p-4",
        confirmed ? "border-emerald-500/40" : "border-border",
      )}
    >
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {phaseTag(decision)}
      </div>
      <p className="mt-1 text-[15px] font-medium leading-snug text-foreground [overflow-wrap:anywhere]">
        {decision.question}
      </p>
      <p className="mt-2 text-sm leading-[1.6] text-muted-foreground [overflow-wrap:anywhere]">
        The build uses <span className="font-medium text-foreground">{answer}</span>.
        {decision.plain && <> {decision.plain}</>}
      </p>
      {decision.confirm_reason && (
        <p className="mt-1.5 text-sm leading-[1.6] text-muted-foreground [overflow-wrap:anywhere]">
          <span className="text-foreground">Why confirm: </span>
          {decision.confirm_reason}
        </p>
      )}
      {(decision.check_at || decision.correct_looks_like) && (
        <dl className="mt-2 grid gap-x-4 gap-y-1 text-[12px] text-muted-foreground sm:grid-cols-2">
          {decision.check_at && (
            <div className="min-w-0">
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80">
                Where to check it
              </dt>
              <dd className="[overflow-wrap:anywhere]">{decision.check_at}</dd>
            </div>
          )}
          {decision.correct_looks_like && (
            <div className="min-w-0">
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80">
                What right looks like
              </dt>
              <dd className="[overflow-wrap:anywhere]">{decision.correct_looks_like}</dd>
            </div>
          )}
        </dl>
      )}

      <div className="mt-auto pt-3">
        {confirmed && (
          <p className="mb-2 inline-flex items-center gap-1.5 text-sm text-emerald-400">
            <CheckCircle2 size={14} aria-hidden />
            Confirmed{edit?.decided_by_name ? ` by ${edit.decided_by_name}` : ""}
          </p>
        )}
        {changedBy && (
          <p className="mb-2 text-sm text-sky-400">Changed by {changedBy}</p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {!confirmed && (
            <button
              type="button"
              onClick={confirm}
              disabled={busy || !canSubmit}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "Confirming…" : "Confirm"}
            </button>
          )}
          <button
            type="button"
            onClick={() => setChanging((v) => !v)}
            aria-expanded={changing}
            className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:bg-accent/40"
          >
            <ChevronRight
              size={13}
              aria-hidden
              className={cn("transition-transform", changing && "rotate-90")}
            />
            {changing ? "Close" : "Change it"}
          </button>
        </div>
        {error && <p className="mt-2 text-sm text-rose-400">{error}</p>}
      </div>

      {changing && (
        <div className="mt-3 overflow-hidden rounded-md border border-border/70">
          <DecisionItem
            decision={decision}
            open
            onToggle={() => setChanging(false)}
            reactions={reactions}
            edit={edit}
            identity={identity}
            setIdentity={setIdentity}
            viewerIsMember={viewerIsMember}
            identityKnown={identityKnown}
            canSubmit={canSubmit}
            onReact={onReact}
            onEdit={onEdit}
          />
        </div>
      )}
    </li>
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
 * Leads with the ordinal and name the Workbench's `PhaseTile` shows.
 */
function PhaseSection({
  group,
  open,
  onToggle,
  changed,
  children,
}: {
  group: PhaseGroup;
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
