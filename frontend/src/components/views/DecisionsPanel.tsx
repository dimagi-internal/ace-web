import { useMemo, useState } from "react";
import { AlertTriangle, ChevronRight, HelpCircle } from "lucide-react";

import type { Decision, SavedDecisionOverride } from "@/api/types.ws";
import { cn } from "@/lib/utils";

import type { EditOp } from "./decisions/decisionsReducer";

interface Props {
  /** The phase whose decisions we want to show — match `Decision.phase`. */
  phase: string;
  /** All decisions on the run — we filter to this phase. */
  decisions: Decision[];
  /**
   * Local edit buffer (per-row staged answer overrides). Pass alongside
   * `onEdit` + `onRevert` to enable inline edit affordance. When any of the
   * three are omitted, the panel renders read-only (legacy behavior).
   */
  editBuffer?: readonly EditOp[];
  /**
   * Durable overrides from `<opp>/inputs/decision-overrides.yaml`, keyed
   * by row id. Per-row precedence: pending buffer edit > saved override >
   * committed run override > AI default.
   */
  savedOverrides?: Record<string, SavedDecisionOverride>;
  /**
   * Commit an override for a row. `new_answer` may be a new option not in
   * `decision.options_considered` — the write path appends it to options
   * before setting override. `override_reasoning` is optional free text.
   */
  onEdit?: (row_id: string, new_answer: string, override_reasoning?: string) => void;
  onRevert?: (row_id: string) => void;
}

/**
 * Per-phase rollup of the decisions log.
 *
 * Each row is a load-bearing question + the AI default + alternatives
 * considered + a status (ai-default | overridden). Rows carry a
 * ``phase`` tag so we can group them per phase here.
 */
const STATUS_RANK: Record<Decision["status"], number> = {
  overridden: 0,
  "ai-default": 1,
};

export function DecisionsPanel({
  phase,
  decisions,
  editBuffer,
  savedOverrides,
  onEdit,
  onRevert,
}: Props) {
  const phaseRows = useMemo(
    () =>
      decisions
        .filter((d) => d.phase === phase)
        .map((d, i) => ({ d, i }))
        .sort((a, b) => {
          const r = STATUS_RANK[a.d.status] - STATUS_RANK[b.d.status];
          return r !== 0 ? r : a.i - b.i;
        })
        .map((x) => x.d),
    [decisions, phase],
  );

  if (phaseRows.length === 0) return null;

  const overridden = phaseRows.filter((d) => d.status === "overridden").length;

  return (
    <DecisionsPanelInner
      phaseRows={phaseRows}
      overridden={overridden}
      editBuffer={editBuffer}
      savedOverrides={savedOverrides}
      onEdit={onEdit}
      onRevert={onRevert}
    />
  );
}

function DecisionsPanelInner({
  phaseRows,
  overridden,
  editBuffer,
  savedOverrides,
  onEdit,
  onRevert,
}: {
  phaseRows: Decision[];
  overridden: number;
  editBuffer?: readonly EditOp[];
  savedOverrides?: Record<string, SavedDecisionOverride>;
  onEdit?: (row_id: string, new_answer: string, override_reasoning?: string) => void;
  onRevert?: (row_id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <section className="mt-3 rounded-lg border border-border bg-card/30">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className={cn(
          "flex w-full items-center gap-2.5 px-4 py-2.5 text-left",
          expanded ? "border-b border-border/70" : "",
        )}
      >
        <span className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-400">
          <HelpCircle className="h-3 w-3" />
          Decisions
        </span>
        <span className="text-xs font-medium text-foreground">{phaseRows.length}</span>
        <span className="ml-auto flex items-center gap-2 text-[11px]">
          {overridden > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-sky-400">
              {overridden} overridden
            </span>
          )}
        </span>
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            expanded ? "rotate-90 text-foreground" : "",
          )}
        />
      </button>
      {expanded && (
        <ul className="divide-y divide-border/60">
          {phaseRows.map((d) => (
            <li key={d.id}>
              <DecisionRow
                decision={d}
                editBuffer={editBuffer}
                savedOverride={savedOverrides?.[d.id]}
                onEdit={onEdit}
                onRevert={onRevert}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function DecisionRow({
  decision,
  editBuffer,
  savedOverride,
  onEdit,
  onRevert,
}: {
  decision: Decision;
  editBuffer?: readonly EditOp[];
  savedOverride?: SavedDecisionOverride;
  onEdit?: (row_id: string, new_answer: string, override_reasoning?: string) => void;
  onRevert?: (row_id: string) => void;
}) {
  const [rowOpen, setRowOpen] = useState(false);
  // Edit-mode draft. Holds in-progress text for the override reasoning and
  // the new-option field. `null` = not in edit mode. Pill selection is NOT
  // drafted — picking a pill stages the edit immediately (radio semantics).
  const [draft, setDraft] = useState<{
    new_option: string;
    override_reasoning: string;
  } | null>(null);

  const pendingEdit = editBuffer?.find((e) => e.row_id === decision.id);
  const committedAnswer = decision.override || decision.ai_default;
  // Precedence: pending buffer edit > saved override (durable file in
  // inputs/) > committed run override > AI default.
  const effectiveValue =
    pendingEdit?.new_answer ?? savedOverride?.override ?? committedAnswer;
  const effectiveReason =
    pendingEdit?.override_reasoning ??
    (savedOverride ? (savedOverride.reasoning ?? "") : (decision.override_reasoning ?? ""));
  const isEdited = !!pendingEdit;
  // "Overridden" = effective answer differs from AI default (whether from a
  // committed override on the run, or a pending edit). Colors the row
  // background so it reads at a glance against the ai-default majority.
  const isOverridden = effectiveValue !== decision.ai_default;
  const canEdit = !!onEdit;

  // Status chip: three-state derivation from the EFFECTIVE state, not a
  // passthrough of `decision.status` — otherwise the chip keeps reading
  // ai-default while a staged pick already highlights a different pill.
  //   ai-default (emerald)          — effective value equals ai_default, no reasoning
  //   overridden (sky)              — committed on the run (or saved to Drive)
  //   overridden · pending (violet) — staged in the shared buffer only
  const effectiveIsAiDefault =
    effectiveValue === decision.ai_default && !effectiveReason;
  const chipLabel = effectiveIsAiDefault
    ? "ai-default"
    : isEdited
      ? "overridden · pending"
      : "overridden";
  const tone = effectiveIsAiDefault
    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
    : isEdited
      ? "border-violet-500/40 bg-violet-500/10 text-violet-400"
      : "border-sky-500/40 bg-sky-500/10 text-sky-400";

  // Row-level color flip: visible sky-tint on overridden rows (committed
  // or pending) so the user can scan a long list and spot the humans'
  // choices vs the AI-default majority. Pending-edit rows additionally
  // get a violet left-border to call out "not yet committed". Tint
  // opacities tuned against dark mode — sky-500/15 reads as a clear band
  // without overpowering the row contents.
  const rowTint = isOverridden
    ? isEdited
      ? "border-l-2 border-violet-500/60 bg-sky-500/15"
      : "bg-sky-500/15"
    : "";

  function openEditMode() {
    setDraft({
      new_option: "",
      override_reasoning: effectiveReason,
    });
  }

  function closeEditMode() {
    setDraft(null);
  }

  // Stage an answer immediately — a pill click behaves like a radio
  // button. An in-progress draft reason travels with the pick so typing
  // a reason first and picking a pill second loses nothing.
  function pickOption(opt: string) {
    if (!onEdit) return;
    if (opt === effectiveValue) return; // radio semantics: no-op
    const reason = (draft ? draft.override_reasoning : effectiveReason).trim();
    if (opt === decision.ai_default && !reason) {
      // Landing back on the AI default with no reasoning is a revert,
      // not an override-to-the-same-value.
      if (isEdited && onRevert) onRevert(decision.id);
      else onEdit(decision.id, opt, undefined);
    } else {
      onEdit(decision.id, opt, reason || undefined);
    }
    if (draft?.new_option) setDraft({ ...draft, new_option: "" });
  }

  // Blur handler for the reason textarea + new-option input. New-option
  // text wins over the current pill value — typing there is the only way
  // to introduce an answer that wasn't on the AI's list.
  function commitDraft() {
    if (!draft || !onEdit) return;
    const answer = draft.new_option.trim() || effectiveValue;
    const reason = draft.override_reasoning.trim();
    // If the user lands on the AI default with no reason, revert
    // outright. Otherwise stage the (possibly equal-to-default) value
    // with the reason attached — the reason itself is a meaningful
    // signal even when the answer doesn't change.
    if (answer === decision.ai_default && !reason) {
      if (isEdited && onRevert) onRevert(decision.id);
      return;
    }
    // Skip no-op writes so tabbing through the fields doesn't spam the
    // shared buffer with identical edits.
    if (answer === effectiveValue && reason === effectiveReason.trim()) return;
    onEdit(decision.id, answer, reason || undefined);
  }

  return (
    <div className={rowTint}>
      <button
        type="button"
        onClick={() =>
          setRowOpen((v) => {
            const next = !v;
            if (!next) closeEditMode();
            return next;
          })
        }
        aria-expanded={rowOpen}
        className="flex w-full items-center gap-3 px-4 py-2 text-left text-xs hover:bg-accent/40"
      >
        <span className="font-mono text-[10px] text-muted-foreground/70">{decision.id}</span>
        <span className="flex-1 truncate text-foreground">{decision.question}</span>
        <span className="hidden truncate text-[11px] text-muted-foreground sm:block sm:max-w-[260px]">
          → <span className="font-medium text-foreground">{effectiveValue}</span>
        </span>
        {isEdited && (
          <span
            className="shrink-0 rounded-full border border-violet-500/40 bg-violet-500/10 px-2 py-0.5 text-[10px] font-semibold text-violet-400"
            aria-label="this row has a pending edit"
          >
            edited{pendingEdit?.editor_name ? ` by ${pendingEdit.editor_name}` : ""}
          </span>
        )}
        {decision.evidence_basis === "conflicting" ? (
          <span
            className="inline-flex shrink-0 items-center gap-1 rounded border border-amber-500/50 bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-400"
            title="The sources disagreed — this default resolved a contested fork"
          >
            <AlertTriangle className="h-3 w-3" />
            conflicting
          </span>
        ) : decision.evidence_basis === "inferred" ? (
          <span
            className="shrink-0 rounded border border-border bg-muted/40 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"
            title="Extrapolated beyond what the source directly states"
          >
            inferred
          </span>
        ) : null}
        <span
          className={cn(
            "shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
            tone,
          )}
        >
          {chipLabel}
        </span>
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            rowOpen ? "rotate-90 text-foreground" : "",
          )}
        />
      </button>
      {rowOpen && (
        <div className="animate-in fade-in slide-in-from-top-1 grid grid-cols-[120px_1fr] gap-x-4 gap-y-2 border-t border-border/40 bg-background/30 px-4 pb-3 pt-3 text-[11px] duration-150">
          <DetailRow
            label="AI default"
            value={<span className="font-medium text-foreground">{decision.ai_default}</span>}
          />
          {decision.override && (
            <DetailRow
              label="Override"
              value={<span className="font-medium text-sky-400">{decision.override}</span>}
            />
          )}
          <DetailRow
            label={canEdit ? "Pick option" : "Options"}
            value={
              <OptionsRow
                decision={decision}
                draft={draft}
                effectiveValue={effectiveValue}
                canEdit={canEdit}
                onPick={pickOption}
              />
            }
          />
          {decision.source && (
            <DetailRow
              label="Source"
              value={<span className="text-muted-foreground">{decision.source}</span>}
            />
          )}
          {decision.evidence_basis !== "stated" && (
            <DetailRow
              label="Evidence basis"
              value={
                <span
                  className={cn(
                    "font-medium",
                    decision.evidence_basis === "conflicting"
                      ? "text-amber-400"
                      : "text-muted-foreground",
                  )}
                >
                  {decision.evidence_basis}
                </span>
              }
            />
          )}
          {decision.evidence_basis === "conflicting" &&
            decision.conflict_signals.length > 0 && (
              <DetailRow
                label="Conflicting source signals"
                value={
                  <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
                    {decision.conflict_signals.map((signal, i) => (
                      <li key={i}>{signal}</li>
                    ))}
                  </ul>
                }
              />
            )}
          <DetailRow
            label="Raised by"
            value={
              <span className="font-mono text-[10px] text-muted-foreground/80">{decision.skill}</span>
            }
          />
          {decision.notes && (
            <DetailRow
              label="AI reasoning"
              value={<span className="whitespace-pre-line text-muted-foreground">{decision.notes}</span>}
            />
          )}
          {effectiveReason && !draft && (
            <DetailRow
              label="Override reason"
              value={<span className="whitespace-pre-line text-sky-400/90">{effectiveReason}</span>}
            />
          )}
          {canEdit && (
            <div className="col-span-2 mt-2 flex flex-col gap-2 border-t border-border/40 pt-3">
              {!draft && (
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={openEditMode}
                    className="rounded-md border border-border bg-background px-3 py-1 text-xs hover:bg-accent"
                  >
                    {effectiveReason ? "Edit override reason" : "Add override reason"}
                  </button>
                  {isEdited && onRevert && (
                    <button
                      type="button"
                      onClick={() => onRevert(decision.id)}
                      className="rounded-md border border-border bg-background px-3 py-1 text-xs hover:bg-accent"
                    >
                      Revert
                    </button>
                  )}
                </div>
              )}
              {draft && (
                <div className="flex w-full flex-col gap-2">
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80">
                      Override reason (optional — saves when you click away)
                    </span>
                    <textarea
                      value={draft.override_reasoning}
                      onChange={(e) =>
                        setDraft({ ...draft, override_reasoning: e.target.value })
                      }
                      onBlur={commitDraft}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") {
                          e.preventDefault();
                          closeEditMode();
                        } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                          e.preventDefault();
                          commitDraft();
                          closeEditMode();
                        }
                      }}
                      autoFocus
                      rows={2}
                      aria-label={`Override reason for: ${decision.question}`}
                      className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80">
                      New option (optional — overrides pill choice)
                    </span>
                    <input
                      type="text"
                      value={draft.new_option}
                      onChange={(e) => setDraft({ ...draft, new_option: e.target.value })}
                      onBlur={commitDraft}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") {
                          e.preventDefault();
                          closeEditMode();
                        } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                          e.preventDefault();
                          commitDraft();
                          closeEditMode();
                        }
                      }}
                      placeholder={
                        decision.options_considered.length > 0
                          ? "Type a new answer not in the list above"
                          : "Type the override answer"
                      }
                      aria-label={`New option for: ${decision.question}`}
                      className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs"
                    />
                  </label>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={closeEditMode}
                      className="rounded-md border border-border bg-background px-3 py-1 text-xs hover:bg-accent"
                    >
                      Done
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function OptionsRow({
  decision,
  draft,
  effectiveValue,
  canEdit,
  onPick,
}: {
  decision: Decision;
  draft: { new_option: string } | null;
  effectiveValue: string;
  canEdit: boolean;
  onPick: (opt: string) => void;
}) {
  // The staged/committed answer highlights UNLESS the user has typed
  // text into the new-option field — then no pill highlights, because
  // the new option will become the staged answer on blur.
  const highlighted =
    draft && draft.new_option.trim().length > 0 ? null : effectiveValue;

  // Surface write-in answers as extra pills so the user sees the current
  // selection somewhere in the pill row, not just in the row header chip.
  // Sources:
  //   (a) the saved override has a value that wasn't in the AI's original
  //       options[] (e.g. a committed write-in from a prior session)
  //   (b) the draft has new_option text the user is currently typing
  // Each surfaces as a violet-tinted pill with a "(new)" tag so it's
  // visually distinct from the AI-proposed options.
  const writeInPills: string[] = [];
  if (
    effectiveValue &&
    effectiveValue !== decision.ai_default &&
    !decision.options_considered.includes(effectiveValue)
  ) {
    writeInPills.push(effectiveValue);
  }
  const draftWriteIn = draft?.new_option.trim() ?? "";
  if (
    draftWriteIn &&
    !decision.options_considered.includes(draftWriteIn) &&
    !writeInPills.includes(draftWriteIn)
  ) {
    writeInPills.push(draftWriteIn);
  }

  if (decision.options_considered.length === 0 && writeInPills.length === 0) {
    return (
      <span className="text-muted-foreground/70">
        (none listed — use the "New option" field to add one)
      </span>
    );
  }
  return (
    <span className="flex flex-wrap gap-1.5">
      {decision.options_considered.map((opt) => {
        const isPicked = opt === highlighted;
        const isAiDefault = opt === decision.ai_default;
        const base = "rounded border px-1.5 py-0.5";
        const tone = isPicked
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
          : "border-border bg-muted/30 text-muted-foreground";
        if (!canEdit) {
          return (
            <span key={opt} className={cn(base, tone)}>
              {opt}
            </span>
          );
        }
        return (
          <button
            key={opt}
            type="button"
            onClick={() => onPick(opt)}
            aria-pressed={isPicked}
            title={isAiDefault ? "AI default" : "Pick this option"}
            className={cn(
              base,
              tone,
              "transition hover:border-emerald-500/40 hover:text-emerald-300",
              isPicked && "ring-1 ring-emerald-400/50",
            )}
          >
            {opt}
            {isAiDefault && (
              <span className="ml-1 text-[9px] uppercase tracking-wider text-muted-foreground/60">
                ai
              </span>
            )}
          </button>
        );
      })}
      {writeInPills.map((opt) => {
        // Write-in pills are display-only (clicking them re-selects the
        // existing write-in, which is the current state — no-op). The
        // "(new)" tag tells the human this label wasn't in the AI's
        // options[] array.
        const isPicked = opt === highlighted || opt === draftWriteIn;
        const base = "rounded border px-1.5 py-0.5";
        const tone = isPicked
          ? "border-violet-500/50 bg-violet-500/15 text-violet-300"
          : "border-violet-500/30 bg-violet-500/[0.08] text-violet-400";
        return (
          <span
            key={`writein:${opt}`}
            className={cn(base, tone)}
            title="Write-in answer not in the original AI options"
          >
            {opt}
            <span className="ml-1 text-[9px] uppercase tracking-wider text-violet-400/70">
              new
            </span>
          </span>
        );
      })}
    </span>
  );
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80">
        {label}
      </div>
      <div className="min-w-0">{value}</div>
    </>
  );
}
