import { useMemo, useState } from "react";
import { ChevronRight, HelpCircle } from "lucide-react";

import type { Decision } from "@/api/types.ws";
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
  onEdit?: (row_id: string, new_answer: string) => void;
  onRevert?: (row_id: string) => void;
}

/**
 * Per-phase rollup of the decisions log.
 *
 * Each row is a load-bearing question + the AI default + alternatives
 * considered + a status (ai-default | overridden). Rows carry a
 * ``phase`` tag so we can group them per phase here.
 */
function parseOption(raw: string): { label: string; explanation: string; raw: string } {
  let idx = raw.indexOf(" — ");
  if (idx < 0) idx = raw.indexOf(" – ");
  if (idx > 0) return { label: raw.slice(0, idx), explanation: raw.slice(idx + 3), raw };
  return { label: raw, explanation: "", raw };
}

const STATUS_RANK: Record<Decision["status"], number> = {
  overridden: 0,
  "ai-default": 1,
};

export function DecisionsPanel({ phase, decisions, editBuffer, onEdit, onRevert }: Props) {
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
      onEdit={onEdit}
      onRevert={onRevert}
    />
  );
}

function DecisionsPanelInner({
  phaseRows,
  overridden,
  editBuffer,
  onEdit,
  onRevert,
}: {
  phaseRows: Decision[];
  overridden: number;
  editBuffer?: readonly EditOp[];
  onEdit?: (row_id: string, new_answer: string) => void;
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
  onEdit,
  onRevert,
}: {
  decision: Decision;
  editBuffer?: readonly EditOp[];
  onEdit?: (row_id: string, new_answer: string) => void;
  onRevert?: (row_id: string) => void;
}) {
  const [rowOpen, setRowOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [customMode, setCustomMode] = useState(false);

  const pendingEdit = editBuffer?.find((e) => e.row_id === decision.id);
  const effectiveValue = pendingEdit?.new_answer ?? (decision.override || decision.ai_default);
  const isEdited = !!pendingEdit;

  const parsedOptions = useMemo(
    () => decision.options.map(parseOption),
    [decision.options],
  );

  const tone =
    decision.status === "overridden"
      ? "border-sky-500/40 bg-sky-500/10 text-sky-400"
      : "border-emerald-500/30 bg-emerald-500/10 text-emerald-400";

  const startEditing = () => {
    const matchesOption = parsedOptions.some((o) => o.label === effectiveValue);
    setDraft(effectiveValue);
    setCustomMode(!matchesOption);
    setEditing(true);
  };

  return (
    <div
      className={cn(
        isEdited && "border-l-2 border-violet-500/60 bg-violet-500/[0.03]",
      )}
    >
      <button
        type="button"
        onClick={() =>
          setRowOpen((v) => {
            const next = !v;
            if (!next) {
              setEditing(false);
              setDraft("");
              setCustomMode(false);
            }
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
        <span
          className={cn(
            "shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
            tone,
          )}
        >
          {decision.status}
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
          {parsedOptions.length > 0 && (
            <DetailRow
              label="Options"
              value={
                <div className="flex flex-col gap-1.5">
                  {parsedOptions.map(({ label, explanation, raw }) => (
                    <div key={raw}>
                      <span
                        className={cn(
                          "inline-block rounded border px-1.5 py-0.5 text-[11px] font-medium",
                          label === effectiveValue
                            ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
                            : "border-border bg-muted/30 text-muted-foreground",
                        )}
                      >
                        {label}
                      </span>
                      {explanation && (
                        <p className="mt-0.5 pl-0.5 text-[10px] leading-relaxed text-muted-foreground/70">
                          {explanation}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              }
            />
          )}
          {decision.source && (
            <DetailRow
              label="Source"
              value={<span className="text-muted-foreground">{decision.source}</span>}
            />
          )}
          <DetailRow
            label="Raised by"
            value={
              <span className="font-mono text-[10px] text-muted-foreground/80">{decision.skill}</span>
            }
          />
          {decision.reasoning && (
            <DetailRow
              label="Reasoning"
              value={<span className="whitespace-pre-line text-muted-foreground">{decision.reasoning}</span>}
            />
          )}
          {decision.override_reasoning && (
            <DetailRow
              label="Override reasoning"
              value={<span className="whitespace-pre-line text-muted-foreground">{decision.override_reasoning}</span>}
            />
          )}
          {onEdit && (
            <div className="col-span-2 mt-2 flex flex-col gap-2 border-t border-border/40 pt-3">
              {!editing && (
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={startEditing}
                    className="rounded-md border border-border bg-background px-3 py-1 text-xs hover:bg-accent"
                  >
                    Edit
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
              {editing && (
                <div className="flex w-full flex-col gap-2">
                  {parsedOptions.length > 0 && (
                    <div className="flex flex-col gap-1">
                      {parsedOptions.map(({ label, explanation, raw }) => (
                        <button
                          key={raw}
                          type="button"
                          onClick={() => {
                            setDraft(label);
                            setCustomMode(false);
                          }}
                          className={cn(
                            "rounded border px-2.5 py-1.5 text-left text-xs transition-colors",
                            draft === label && !customMode
                              ? "border-emerald-500/40 bg-emerald-500/10"
                              : "border-border bg-muted/30 hover:bg-accent/40",
                          )}
                        >
                          <span
                            className={cn(
                              "font-medium",
                              draft === label && !customMode
                                ? "text-emerald-400"
                                : "text-foreground",
                            )}
                          >
                            {label}
                          </span>
                          {explanation && (
                            <span className="mt-0.5 block text-[10px] text-muted-foreground/70">
                              {explanation}
                            </span>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      setCustomMode(true);
                      if (!customMode) setDraft("");
                    }}
                    className={cn(
                      "rounded border px-2.5 py-1.5 text-left text-xs transition-colors",
                      customMode
                        ? "border-violet-500/40 bg-violet-500/10 text-violet-400 font-medium"
                        : "border-border bg-muted/30 text-muted-foreground hover:bg-accent/40",
                    )}
                  >
                    Custom answer
                  </button>
                  {customMode && (
                    <input
                      type="text"
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") {
                          e.preventDefault();
                          setEditing(false);
                          setCustomMode(false);
                        } else if (e.key === "Enter") {
                          e.preventDefault();
                          if (draft.trim()) {
                            onEdit(decision.id, draft.trim());
                            setEditing(false);
                            setCustomMode(false);
                          }
                        }
                      }}
                      autoFocus
                      placeholder="Enter custom answer…"
                      className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs"
                    />
                  )}
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        if (draft.trim()) {
                          onEdit(decision.id, draft.trim());
                          setEditing(false);
                          setCustomMode(false);
                        }
                      }}
                      disabled={!draft.trim()}
                      className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-40"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setEditing(false);
                        setCustomMode(false);
                      }}
                      className="rounded-md border border-border bg-background px-3 py-1 text-xs hover:bg-accent"
                    >
                      Cancel
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
