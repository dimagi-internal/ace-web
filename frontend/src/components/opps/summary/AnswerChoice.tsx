import { useState } from "react";
import { CheckCircle2 } from "lucide-react";

import type { Decision } from "@/api/types.ws";
import { decisionDisplay } from "@/components/opps/decisions/decisionDisplay";
import { cn } from "@/lib/utils";

/**
 * ONE control for one choice, on the run summary (ace-web#876 item 4).
 *
 * The row used to offer three things for the same act: a Confirm button,
 * option pills with ACE's pick pre-highlighted green and tagged "AI", and
 * a separate "Write in a different answer" editor. A partner could read
 * the green pill as already chosen, or as the button to press.
 *
 * Now it is a radio list: the answer in force is checked, ACE's pick is
 * labelled as such, and "Something else" is the last option. Picking an
 * option still commits as it happens (the 2026-10-03 "click-and-done, no
 * Save" rule); only a typed answer needs a Save, because typing has no
 * natural moment to commit. Below the list, ONE button confirms the answer
 * in force — "keep this" recorded distinctly from a change.
 *
 * The Workbench keeps `DecisionAnswerEditor`; this is the partner surface.
 */
export function AnswerChoice({
  decision,
  answer,
  reason,
  confirmed,
  confirmedBy,
  busy,
  error,
  onConfirm,
  onCommit,
}: {
  decision: Decision;
  /** Answer in force (saved human answer > run override > AI default). */
  answer: string;
  /** Reasoning in force; "" when none. */
  reason: string;
  confirmed: boolean;
  confirmedBy?: string;
  busy: boolean;
  error: string | null;
  onConfirm: () => unknown;
  /** Persist an answer; resolves false when it did not save. */
  onCommit: (value: string, reasoning: string) => Promise<boolean>;
}) {
  const options = decision.options_considered;
  const inList = options.includes(answer);
  const [other, setOther] = useState<string | null>(inList ? null : answer);
  const [why, setWhy] = useState(reason);
  const name = `answer-${decision.id}`;
  const changed = answer !== decision.ai_default;

  function pick(opt: string) {
    setOther(null);
    if (opt === answer) return;
    // Back to ACE's pick with nothing to say is a revert, not a ruling.
    void onCommit(opt, opt === decision.ai_default ? "" : why.trim());
  }

  async function saveOther() {
    const value = (other ?? "").trim();
    if (!value || (value === answer && why.trim() === reason.trim())) return;
    await onCommit(value, why.trim());
  }

  function saveWhy() {
    if (!changed || why.trim() === reason.trim()) return;
    void onCommit(answer, why.trim());
  }

  const optionLabel = (opt: string) => {
    const shown = opt === decision.ai_default ? decisionDisplay(decision, opt).value : "";
    return shown && shown !== opt ? shown : opt;
  };

  return (
    <div className="flex flex-col gap-2 text-[13px]">
      <fieldset className="flex flex-col gap-1" disabled={busy}>
        <legend className="sr-only">Answer for: {decision.question}</legend>
        {options.map((opt) => (
          <label
            key={opt}
            className={cn(
              "flex cursor-pointer items-start gap-2 rounded px-2 py-1.5 hover:bg-accent/40",
              opt === answer && other === null && "bg-emerald-500/10",
            )}
          >
            <input
              type="radio"
              name={name}
              value={opt}
              checked={other === null && opt === answer}
              onChange={() => pick(opt)}
              className="mt-[3px] accent-emerald-500"
            />
            <span className="min-w-0 [overflow-wrap:anywhere]">
              <span className="text-foreground">{optionLabel(opt)}</span>
              {opt === decision.ai_default && (
                <span className="ml-2 text-[11px] text-muted-foreground">ACE's pick</span>
              )}
            </span>
          </label>
        ))}
        <label className="flex cursor-pointer items-start gap-2 rounded px-2 py-1.5 hover:bg-accent/40">
          <input
            type="radio"
            name={name}
            value="__other__"
            checked={other !== null}
            onChange={() => setOther(inList ? "" : answer)}
            className="mt-[3px] accent-emerald-500"
          />
          <span className="text-foreground">
            {options.length > 0 ? "Something else" : "Type the answer"}
          </span>
        </label>
      </fieldset>

      {other !== null && (
        <div className="ml-7 flex flex-col gap-2">
          <input
            type="text"
            value={other}
            onChange={(e) => setOther(e.target.value)}
            maxLength={400}
            autoFocus
            placeholder="Type your answer"
            aria-label={`New option for: ${decision.question}`}
            className="w-full rounded-md border border-border bg-background px-2 py-1"
          />
          <textarea
            value={why}
            onChange={(e) => setWhy(e.target.value)}
            rows={2}
            maxLength={2000}
            placeholder="Why (optional)"
            aria-label={`Override reason for: ${decision.question}`}
            className="w-full rounded-md border border-border bg-background px-2 py-1"
          />
          <div>
            <button
              type="button"
              disabled={busy || !(other ?? "").trim()}
              onClick={() => void saveOther()}
              className="rounded-md bg-primary px-3 py-1 font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "Saving…" : "Save this answer"}
            </button>
          </div>
        </div>
      )}

      {other === null && changed && (
        <label className="ml-7 flex flex-col gap-1">
          <span className="text-[11px] text-muted-foreground">
            Why you changed it (optional — saves when you click away)
          </span>
          <textarea
            value={why}
            onChange={(e) => setWhy(e.target.value)}
            onBlur={saveWhy}
            rows={2}
            maxLength={2000}
            aria-label={`Override reason for: ${decision.question}`}
            className="w-full rounded-md border border-border bg-background px-2 py-1"
          />
        </label>
      )}

      {error && <p className="text-red-400">{error}</p>}

      {other === null && (
        <div className="flex flex-wrap items-center gap-3">
          {confirmed ? (
            <span className="inline-flex items-center gap-1.5 text-emerald-400">
              <CheckCircle2 size={14} aria-hidden />
              Confirmed{confirmedBy ? ` by ${confirmedBy}` : ""}
            </span>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() => void onConfirm()}
              className="rounded-md bg-primary px-3 py-1 font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
              aria-label={`Confirm: ${decisionDisplay(decision, answer).value || answer}`}
            >
              {busy ? "Saving…" : "Confirm this answer"}
            </button>
          )}
          <span className="text-muted-foreground">
            Picking a different option saves it straight away.
          </span>
        </div>
      )}
    </div>
  );
}
