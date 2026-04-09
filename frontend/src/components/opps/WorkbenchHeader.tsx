import type { OppCard, Run, RunSummary } from "../../api/types";
import { RunSwitcher } from "./RunSwitcher";

interface Props {
  opp: OppCard;
  run: Run;
  runs: RunSummary[];
  onRefresh: () => void;
}

export function WorkbenchHeader({ opp, run, runs, onRefresh }: Props) {
  return (
    <div className="flex items-center gap-4 border-b border-zinc-800 bg-zinc-900 px-4 py-2 text-sm">
      <span className="font-semibold text-zinc-100">{opp.display_name || opp.slug}</span>
      <span className="text-zinc-500">
        {run.current_phase ? `Phase · ${run.current_phase}` : "—"}
      </span>
      <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
        {run.mode} mode
      </span>
      <span className="ml-auto flex items-center gap-3">
        <RunSwitcher slug={opp.slug} currentRunId={run.run_id} runs={runs} />
        <button
          type="button"
          onClick={onRefresh}
          className="rounded bg-amber-600 px-3 py-1 text-xs font-semibold text-white hover:bg-amber-700"
        >
          ⟳ refresh from Drive
        </button>
      </span>
    </div>
  );
}
