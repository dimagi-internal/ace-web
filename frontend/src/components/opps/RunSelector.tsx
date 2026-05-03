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

export function RunSelector({ runs, selectedRunId, onChange }: RunSelectorProps) {
  if (runs.length === 0) {
    return <span className="text-xs text-muted-foreground">no runs</span>;
  }

  const selected = runs.find((r) => r.run_id === selectedRunId) ?? runs[0];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex items-center gap-1 rounded border px-2 py-0.5 text-xs hover:bg-accent">
        <span className="font-mono">{selected.run_id}</span>
        {runs.length > 1 && <ChevronDown className="h-3 w-3 text-muted-foreground" />}
      </DropdownMenuTrigger>
      {runs.length > 1 && (
        <DropdownMenuContent align="start" className="w-72 max-h-96 overflow-y-auto">
          {runs.map((r) => (
            <DropdownMenuItem
              key={r.run_id}
              className={r.run_id === selected.run_id ? "bg-accent/50" : ""}
              onClick={() => onChange(r.run_id)}
            >
              <div className="flex flex-col gap-0.5">
                <span className="font-mono text-xs">{r.run_id}</span>
                <span className="text-xs text-muted-foreground">
                  {r.current_phase ?? "?"} / {r.current_step ?? "?"} · {r.mode ?? "?"}
                </span>
              </div>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      )}
    </DropdownMenu>
  );
}
