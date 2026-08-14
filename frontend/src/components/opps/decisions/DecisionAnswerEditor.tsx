import { useState } from "react";

import type { Decision } from "@/api/types.ws";
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
 * Two things are genuinely per-surface, and they are the only two props
 * that differ:
 *
 * - `commitMode`. The Workbench stages into a shared multi-player Redis
 *   buffer that a member later saves to Drive, so a pill click can commit
 *   instantly — nothing is durable yet and Revert/Discard-all are one
 *   click away. The public page writes THROUGH on submit and has to
 *   collect a self-reported identity at that moment, so it stages the
 *   pick locally and confirms. Asking for a name before someone can even
 *   click a pill would be the barrier this surface exists to remove.
 * - `identitySlot` / `dense`. Who is asked for a name, and the type scale
 *   (a console vs a document a partner reads).
 */
export type CommitMode = "immediate" | "confirm";

/**
 * Per-surface copy. The mechanics are identical; the words are not, and
 * pretending otherwise would be a worse kind of sharing. "Override
 * reason" is the Workbench's established vocabulary and matches the field
 * this writes (`override_reasoning`); a partner reading a summary page
 * has never met that word. The FIELD LABELS (aria-label) stay identical
 * across both so assistive tech and tests see one component.
 */
const COPY = {
  immediate: {
    openEdit: "Add override reason",
    editExisting: "Edit override reason",
    revert: "Revert",
    reasonLegend: "Override reason (optional — saves when you click away)",
    writeInLegend: "New option (optional — overrides pill choice)",
    writeInPlaceholder: "Type a new answer not in the list above",
    close: "Done",
  },
  confirm: {
    openEdit: "Write in a different answer",
    editExisting: "Edit this answer",
    revert: "Restore the AI default",
    reasonLegend: "Why (optional)",
    writeInLegend: "A different answer (optional — overrides the pick above)",
    writeInPlaceholder: "Type an answer not in the list above",
    close: "Cancel",
  },
} as const;

export interface DecisionAnswerEditorProps {
  decision: Decision;
  /** Answer currently in force (human override / staged edit / AI default). */
  effectiveValue: string;
  /** Override rationale currently in force; "" when none. */
  effectiveReason: string;
  commitMode: CommitMode;
  onCommit: (value: string, reasoning: string) => void | Promise<void>;
  /** Back to the AI default with nothing to say. Omit to hide the control. */
  onRevert?: () => void | Promise<void>;
  /**
   * Is there anything to undo? The two surfaces know different things:
   * the Workbench means "a pending buffer edit exists" (a saved override
   * is undone through the history block instead), the summary means "a
   * human-set answer is in force". Inferring it from the value would be
   * wrong for a staged edit that happens to equal the AI default.
   * Defaults to "the answer differs from the AI default".
   */
  revertable?: boolean;
  /** Rendered inside the confirm block — the identity fields, publicly. */
  identitySlot?: React.ReactNode;
  /** Blocks submit while true (e.g. a missing self-reported name). */
  canSubmit?: boolean;
  busy?: boolean;
  error?: string | null;
  /** Workbench console type scale rather than the reading scale. */
  dense?: boolean;
}

export function DecisionAnswerEditor({
  decision,
  effectiveValue,
  effectiveReason,
  commitMode,
  onCommit,
  onRevert,
  revertable,
  identitySlot,
  canSubmit = true,
  busy = false,
  error = null,
  dense = false,
}: DecisionAnswerEditorProps) {
  // `null` = not editing. Holds the in-progress pick + text; in
  // `immediate` mode the pick is committed as it happens and this only
  // carries text.
  const [draft, setDraft] = useState<{
    value: string;
    new_option: string;
    reasoning: string;
  } | null>(null);

  const copy = COPY[commitMode];
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
    if (commitMode === "immediate") {
      if (opt === effectiveValue) return; // radio semantics: no-op
      const reasoning = (draft ? draft.reasoning : effectiveReason).trim();
      if (opt === decision.ai_default && !reasoning && onRevert) {
        void onRevert();
      } else {
        void onCommit(opt, reasoning);
      }
      if (draft?.new_option) setDraft({ ...draft, new_option: "" });
      return;
    }
    // confirm mode: stage locally; nothing leaves the browser until the
    // person says so (and, if anonymous, says who they are).
    if (draft) setDraft({ ...draft, value: opt, new_option: "" });
    else begin(opt);
  }

  async function submit() {
    if (!draft || busy) return;
    const value = draft.new_option.trim() || draft.value;
    const reasoning = draft.reasoning.trim();
    if (!value) return;
    if (value === effectiveValue && reasoning === effectiveReason.trim()) {
      setDraft(null);
      return;
    }
    await onCommit(value, reasoning);
    setDraft(null);
  }

  // Immediate mode saves the reason on blur — the Workbench's existing
  // behaviour, which the shared buffer makes safe.
  function commitReasonOnBlur() {
    if (!draft || commitMode !== "immediate") return;
    const value = draft.new_option.trim() || draft.value;
    const reasoning = draft.reasoning.trim();
    if (value === decision.ai_default && !reasoning) {
      if (canRevert && onRevert) void onRevert();
      return;
    }
    if (value === effectiveValue && reasoning === effectiveReason.trim()) return;
    void onCommit(value, reasoning);
  }

  const dirty =
    !!draft &&
    (stagedValue !== effectiveValue || draft.reasoning.trim() !== effectiveReason.trim());

  return (
    <div className={cn("flex flex-col gap-2", text)}>
      <OptionPills
        decision={decision}
        selected={stagedValue}
        editable
        onPick={pick}
      />

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
              onClick={() => void onRevert()}
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
              {copy.reasonLegend}
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
          {commitMode === "confirm" && identitySlot}
          {error && <p className="text-red-400">{error}</p>}
          <div className="flex flex-wrap items-center gap-3">
            {commitMode === "confirm" && (
              <button
                type="button"
                onClick={() => void submit()}
                disabled={!dirty || !canSubmit || busy}
                className={cn(
                  "rounded px-3 py-1.5 font-medium transition",
                  dirty && canSubmit && !busy
                    ? "bg-primary text-primary-foreground hover:opacity-90"
                    : "cursor-not-allowed bg-muted text-muted-foreground",
                )}
              >
                {busy ? "Saving…" : "Save this answer"}
              </button>
            )}
            <button
              type="button"
              onClick={() => setDraft(null)}
              className="rounded-md border border-border bg-background px-3 py-1 hover:bg-accent"
            >
              {copy.close}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
