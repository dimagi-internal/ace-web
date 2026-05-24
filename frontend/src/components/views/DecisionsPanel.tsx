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

  const pendingEdit = editBuffer?.find((e) => e.row_id === decision.id);
  const effectiveValue = pendingEdit?.new_answer ?? (decision.override || decision.ai_default);
  const isEdited = !!pendingEdit;

  const tone =
    decision.status === "overridden"
      ? "border-sky-500/40 bg-sky-500/10 text-sky-400"
      : "border-emerald-500/30 bg-emerald-500/10 text-emerald-400";

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
          {decision.options_considered.length > 0 && (
            <DetailRow
              label="Options considered"
              value={
                <span className="flex flex-wrap gap-1.5">
                  {decision.options_considered.map((opt) => (
                    <span
                      key={opt}
                      className={cn(
                        "rounded border px-1.5 py-0.5",
                        opt === effectiveValue
                          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
                          : "border-border bg-muted/30 text-muted-foreground",
                      )}
                    >
                      {opt}
                    </span>
                  ))}
                </span>
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
          {decision.notes && (
            <DetailRow
              label="Notes"
              value={<span className="whitespace-pre-line text-muted-foreground">{decision.notes}</span>}
            />
          )}
          {onEdit && (
            <div className="col-span-2 mt-2 flex gap-2 border-t border-border/40 pt-3">
              {!editing && (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      setDraft(effectiveValue);
                      setEditing(true);
                    }}
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
                </>
              )}
              {editing && (
                <div className="flex w-full flex-col gap-2">
                  <textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Escape") {
                        e.preventDefault();
                        setEditing(false);
                      } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                        e.preventDefault();
                        onEdit(decision.id, draft);
                        setEditing(false);
                      }
                    }}
                    autoFocus
                    rows={3}
                    aria-label={`Edit answer for: ${decision.question}`}
                    className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs"
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        onEdit(decision.id, draft);
                        setEditing(false);
                      }}
                      className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-400 hover:bg-emerald-500/20"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditing(false)}
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
