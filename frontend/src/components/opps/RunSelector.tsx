import { useState } from "react";
import { ChevronDown, Trash2 } from "lucide-react";

import type { RunSummary } from "../../api/types.ws";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DeleteRunDialog } from "./DeleteRunDialog";

interface RunSelectorProps {
  oppSlug: string;
  runs: RunSummary[];
  selectedRunId: string | null;
  onChange: (runId: string) => void;
  /** Called after a run is trashed so the parent can refetch the snapshot. */
  onRunDeleted?: () => void;
}

// The plugin uses YYYYMMDD-HHMM as the run id (e.g. "20260503-0835").
// Render it as a friendly local datetime when we recognise the format,
// fall back to the raw id otherwise.
const RUN_ID_DATE_RE = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})$/;

function formatRunId(runId: string): string {
  const m = RUN_ID_DATE_RE.exec(runId);
  if (!m) return runId;
  const [, y, mo, d, hh, mm] = m;
  const date = new Date(Number(y), Number(mo) - 1, Number(d), Number(hh), Number(mm));
  if (Number.isNaN(date.getTime())) return runId;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function RunSelector({
  oppSlug,
  runs,
  selectedRunId,
  onChange,
  onRunDeleted,
}: RunSelectorProps) {
  const [deleteTarget, setDeleteTarget] = useState<RunSummary | null>(null);

  if (runs.length === 0) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span className="uppercase tracking-wide text-[10px]">Run</span>
        <span>No runs yet</span>
      </div>
    );
  }

  const selected = runs.find((r) => r.run_id === selectedRunId) ?? runs[0];
  const friendly = formatRunId(selected.run_id);

  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Run</span>
      <DropdownMenu>
        <DropdownMenuTrigger
          className="flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs text-foreground hover:bg-accent"
          title={selected.run_id}
        >
          <span>{friendly}</span>
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-64 max-h-96 overflow-y-auto">
            {runs.map((r) => (
              <DropdownMenuItem
                key={r.run_id}
                className={
                  "flex items-center gap-2 " +
                  (r.run_id === selected.run_id ? "bg-accent/50" : "")
                }
                // Don't auto-close the menu when the user clicks the trash
                // icon (we want the confirm dialog to render on top of the
                // open menu, then the menu can close after).
                onSelect={(e) => e.preventDefault()}
              >
                <button
                  type="button"
                  onClick={() => onChange(r.run_id)}
                  className="flex-1 text-left text-xs"
                  title={r.run_id}
                >
                  {formatRunId(r.run_id)}
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeleteTarget(r);
                  }}
                  className="rounded p-0.5 text-muted-foreground/60 hover:bg-destructive/15 hover:text-destructive"
                  aria-label={`Trash run ${r.run_id}`}
                  title="Trash this run (30-day Drive-recoverable)"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
      </DropdownMenu>
      {deleteTarget && (
        <DeleteRunDialog
          open={true}
          onOpenChange={(v) => {
            if (!v) setDeleteTarget(null);
          }}
          oppSlug={oppSlug}
          runId={deleteTarget.run_id}
          runLabel={formatRunId(deleteTarget.run_id)}
          onDeleted={() => {
            setDeleteTarget(null);
            onRunDeleted?.();
          }}
        />
      )}
    </div>
  );
}
