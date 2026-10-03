import { useState } from "react";

import type { Decision } from "@/api/types.ws";
import { fireAndForget } from "@/components/opps/decisions/fireAndForget";
import { OptionPills } from "@/components/opps/decisions/OptionPills";
import { cn } from "@/lib/utils";

/**
 * Changing a decision's answer — the ONE editor, shared by both surfaces.
 *
 * The Workbench already had an editable decisions panel for authenticated
 * members (pill picker, write-in, override reason, revert), writing
 * `<opp>/inputs/decision-overrides.yaml`, which the plugin binds on the
 * next run. When the public run summary gained the same ability
 * (Jonathan, 2026-08-14 — "reviewer 2 can change / update reviewer 1
 * anyway in the UI, and that should just be the same as Dimagi going in
 * and updating things on top of the anonymous input"), the right move was
 * to generalise this, not to grow a lookalike beside it. A second editor
 * would have drifted on write-in semantics, revert semantics, and what
 * counts as a no-op within a week.
 *
 * Two things vary between the surfaces:
 *
 * - `voice` follows **surface**. "Override reason" is Workbench
 *   vocabulary; a partner reading a summary page has never met the word.
 *   The mechanics are identical, the words are not, and the `aria-label`s
 *   stay identical across both regardless of voice.
 * - `dense` follows **type scale** — the Workbench's console scale vs the
 *   reading scale of a document a partner reads.
 *
 * A pill click commits as it happens on BOTH surfaces. The summary used to
 * have a `confirm` commit mode that staged a pick behind a Save button
 * while an anonymous reviewer typed their name; anonymous editing was
 * removed (2026-10-03 — only signed-in workspace members write), and the
 * mode with it.
 */
/** Whose vocabulary the visible copy speaks. See `COPY`. */
export type EditorVoice = "console" | "partner";

/**
 * Per-surface copy, keyed by VOICE.
 *
 * The mechanics are identical; the words are not, and pretending
 * otherwise would be a worse kind of sharing. "Override reason" is the
 * Workbench's established vocabulary and matches the field this writes
 * (`override_reasoning`); a partner reading a summary page has never met
 * that word. The FIELD LABELS (aria-label) stay identical across both so
 * assistive tech and tests see one component.
 */
const COPY = {
  console: {
    openEdit: "Add override reason",
    editExisting: "Edit override reason",
    revert: "Revert",
    reasonLegend: "Override reason",
    writeInLegend: "New option (optional — overrides pill choice)",
    writeInPlaceholder: "Type a new answer not in the list above",
    close: "Done",
  },
  partner: {
    openEdit: "Write in a different answer",
    editExisting: "Edit this answer",
    revert: "Restore the AI default",
    reasonLegend: "Why",
    writeInLegend: "A different answer (optional — overrides the pick above)",
    writeInPlaceholder: "Type an answer not in the list above",
    close: "Done",
  },
} as const;

export interface DecisionAnswerEditorProps {
  decision: Decision;
  /** Answer currently in force (human override / staged edit / AI default). */
  effectiveValue: string;
  /** Override rationale currently in force; "" when none. */
  effectiveReason: string;
  /** Whose vocabulary the copy speaks — the Workbench's, or a partner's. */
  voice: EditorVoice;
  /**
   * Persist the answer. Returning (or resolving to) `false` means "it did
   * not save" and keeps the draft open with `error` showing; anything
   * else closes it. A REJECTION is also treated as a failure — the
   * caller owns surfacing it through `error`, and letting it escape here
   * would be an unhandled rejection on every failed save.
   */
  onCommit: (value: string, reasoning: string) => unknown;
  /** Back to the AI default with nothing to say. Omit to hide the control. */
  onRevert?: () => unknown;
  /**
   * Is there anything to undo? The two surfaces know different things:
   * the Workbench means "a pending buffer edit exists" (a saved override
   * is undone through the history block instead), the summary means "a
   * human-set answer is in force". Inferring it from the value would be
   * wrong for a staged edit that happens to equal the AI default.
   * Defaults to "the answer differs from the AI default".
   */
  revertable?: boolean;
  busy?: boolean;
  error?: string | null;
  /** Workbench console type scale rather than the reading scale. */
  dense?: boolean;
}

export function DecisionAnswerEditor({
  decision,
  effectiveValue,
  effectiveReason,
  voice,
  onCommit,
  onRevert,
  revertable,
  busy = false,
  error = null,
  dense = false,
}: DecisionAnswerEditorProps) {
  // `null` = not editing. A pick is committed as it happens, so this only
  // carries the in-progress text.
  const [draft, setDraft] = useState<{
    value: string;
    new_option: string;
    reasoning: string;
  } | null>(null);

  const copy = COPY[voice];
  // The reason field saves on blur in immediate mode; say so rather than
  // leaving someone wondering whether their typing was kept.
  const reasonLegend = `${copy.reasonLegend} (optional — saves when you click away)`;
  const closeLabel = copy.close;
  const text = dense ? "text-xs" : "text-[13px]";
  const canRevert = revertable ?? effectiveValue !== decision.ai_default;
  const open = draft !== null;
  const stagedValue = draft ? draft.new_option.trim() || draft.value : effectiveValue;

  function begin(seedValue?: string) {
    setDraft({
      value: seedValue ?? effectiveValue,
      new_option: "",
      reasoning: effectiveReason,
    });
  }

  function pick(opt: string) {
    if (opt === effectiveValue) return; // radio semantics: no-op
    const reasoning = (draft ? draft.reasoning : effectiveReason).trim();
    if (opt === decision.ai_default && !reasoning && onRevert) {
      fireAndForget(onRevert());
    } else {
      fireAndForget(onCommit(opt, reasoning));
    }
    if (draft?.new_option) setDraft({ ...draft, new_option: "" });
  }

  // The reason saves on blur — the Workbench's existing behaviour.
  function commitReasonOnBlur() {
    if (!draft) return;
    const value = draft.new_option.trim() || draft.value;
    const reasoning = draft.reasoning.trim();
    if (value === decision.ai_default && !reasoning) {
      if (canRevert && onRevert) fireAndForget(onRevert());
      return;
    }
    if (value === effectiveValue && reasoning === effectiveReason.trim()) return;
    fireAndForget(onCommit(value, reasoning));
  }

  return (
    <div className={cn("flex flex-col gap-2", text)}>
      <OptionPills
        decision={decision}
        selected={stagedValue}
        editable
        onPick={pick}
      />

      {/* There is no draft block to hang these off, and a pill click that
          failed server-side would otherwise be silently lost — the row
          would just snap back. */}
      {!open && busy && (
        <p className="text-muted-foreground" role="status">
          Saving…
        </p>
      )}
      {!open && error && <p className="text-red-400">{error}</p>}

      {!open && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => begin()}
            className="rounded-md border border-border bg-background px-3 py-1 hover:bg-accent"
          >
            {effectiveReason ? copy.editExisting : copy.openEdit}
          </button>
          {canRevert && onRevert && (
            <button
              type="button"
              onClick={() => fireAndForget(onRevert())}
              className="rounded-md border border-border bg-background px-3 py-1 hover:bg-accent"
            >
              {copy.revert}
            </button>
          )}
        </div>
      )}

      {open && (
        <div className="flex w-full flex-col gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80">
              {reasonLegend}
            </span>
            <textarea
              value={draft.reasoning}
              onChange={(e) => setDraft({ ...draft, reasoning: e.target.value })}
              onBlur={commitReasonOnBlur}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.preventDefault();
                  setDraft(null);
                }
              }}
              rows={2}
              maxLength={2000}
              aria-label={`Override reason for: ${decision.question}`}
              className="w-full rounded-md border border-border bg-background px-2 py-1"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80">
              {copy.writeInLegend}
            </span>
            <input
              type="text"
              value={draft.new_option}
              onChange={(e) => setDraft({ ...draft, new_option: e.target.value })}
              onBlur={commitReasonOnBlur}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.preventDefault();
                  setDraft(null);
                }
              }}
              maxLength={400}
              placeholder={
                decision.options_considered.length > 0
                  ? copy.writeInPlaceholder
                  : "Type the answer"
              }
              aria-label={`New option for: ${decision.question}`}
              className="w-full rounded-md border border-border bg-background px-2 py-1"
            />
          </label>
          {error && <p className="text-red-400">{error}</p>}
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => setDraft(null)}
              className="rounded-md border border-border bg-background px-3 py-1 hover:bg-accent"
            >
              {closeLabel}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
