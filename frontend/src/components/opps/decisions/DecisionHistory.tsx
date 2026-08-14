import { useState } from "react";
import { ChevronRight, RotateCcw, ShieldCheck } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Who changed this row, when, and what it used to say.
 *
 * This is not decoration. Anyone with the link can change a decision's
 * value in place — no account, no proposal state, no promotion step —
 * and the thing that makes that safe is that every change is attributed
 * and every prior value is one click from being restored. Exactly the
 * model a Google Doc with anyone-with-link editing runs on, which is what
 * the PDD these decisions summarize already is. If the history stopped
 * being visible and reversible, the edit model would stop being safe.
 *
 * `verified` distinguishes a signed-in member from a self-reported name.
 * It is shown, never enforced: reviewer 2 changing reviewer 1's answer
 * and Dimagi changing either are the same act.
 */
export interface DecisionEditEntry {
  override: string;
  reasoning?: string;
  decided_by_name?: string;
  decided_by_verified?: boolean;
  decided_at?: string;
}

export function formatEditedAt(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.valueOf())) return "";
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function EditorName({
  name,
  verified,
}: {
  name?: string;
  verified?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-1">
      {name || "Anonymous"}
      {verified ? (
        <ShieldCheck
          size={11}
          className="text-emerald-400/80"
          aria-label="signed in"
        />
      ) : (
        <span
          className="text-muted-foreground/50"
          title="Name typed by the person making the change, not verified"
        >
          (self-reported)
        </span>
      )}
    </span>
  );
}

export function DecisionHistory({
  current,
  history,
  onRestore,
}: {
  current: DecisionEditEntry;
  history: DecisionEditEntry[];
  /** Undo — writes the old value back as a new, attributed change. */
  onRestore?: (value: string, reasoning: string) => void | Promise<void>;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="mt-3 rounded border border-border/70 bg-muted/20 px-3 py-2 text-[12px]">
      <p className="text-muted-foreground">
        Changed to <span className="font-medium text-foreground">{current.override}</span>{" "}
        by{" "}
        <EditorName
          name={current.decided_by_name}
          verified={current.decided_by_verified}
        />
        {current.decided_at && <> · {formatEditedAt(current.decided_at)}</>}
      </p>
      {/* The CURRENT reasoning is not repeated here — `DecisionDetailFields`
          already renders it as the "Override reason" row on both surfaces,
          and showing it twice reads as two conflicting fields. This block
          owns attribution and the past. */}
      {history.length > 0 && (
        <>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="mt-1.5 inline-flex items-center gap-1 text-muted-foreground underline-offset-4 hover:underline"
          >
            <ChevronRight
              size={12}
              className={cn("transition-transform", open && "rotate-90")}
            />
            {open ? "Hide" : `${history.length} earlier `}
            {open ? "earlier answers" : history.length === 1 ? "answer" : "answers"}
          </button>
          {open && (
            <ul className="mt-2 space-y-1.5 border-t border-border/60 pt-2">
              {history.map((h, i) => (
                <li
                  key={`${h.decided_at}-${i}`}
                  className="flex flex-wrap items-baseline gap-x-2 gap-y-1"
                >
                  <span className="font-medium text-foreground">{h.override}</span>
                  <span className="text-muted-foreground">
                    <EditorName
                      name={h.decided_by_name}
                      verified={h.decided_by_verified}
                    />
                    {h.decided_at && <> · {formatEditedAt(h.decided_at)}</>}
                  </span>
                  {onRestore && (
                    <button
                      type="button"
                      onClick={() => void onRestore(h.override, h.reasoning ?? "")}
                      className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 hover:bg-accent"
                    >
                      <RotateCcw size={10} />
                      Restore
                    </button>
                  )}
                  {h.reasoning && (
                    <span className="w-full whitespace-pre-line text-muted-foreground/80">
                      {h.reasoning}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
