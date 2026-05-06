import { ChevronDown } from "lucide-react";

import type { RunSummary } from "../../api/types";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface RunSelectorProps {
  runs: RunSummary[];
  selectedRunId: string | null;
  onChange: (runId: string) => void;
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

export function RunSelector({ runs, selectedRunId, onChange }: RunSelectorProps) {
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
          className="flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs text-foreground hover:bg-accent disabled:cursor-default disabled:opacity-100"
          title={selected.run_id}
          disabled={runs.length <= 1}
        >
          <span>{friendly}</span>
          {runs.length > 1 && <ChevronDown className="h-3 w-3 text-muted-foreground" />}
        </DropdownMenuTrigger>
        {runs.length > 1 && (
          <DropdownMenuContent align="start" className="w-64 max-h-96 overflow-y-auto">
            {runs.map((r) => (
              <DropdownMenuItem
                key={r.run_id}
                className={r.run_id === selected.run_id ? "bg-accent/50" : ""}
                onClick={() => onChange(r.run_id)}
              >
                <span className="text-xs" title={r.run_id}>
                  {formatRunId(r.run_id)}
                </span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        )}
      </DropdownMenu>
    </div>
  );
}
