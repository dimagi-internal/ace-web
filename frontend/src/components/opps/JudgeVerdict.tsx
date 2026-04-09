import type { Judge } from "../../api/types";

export function JudgeVerdict({ judge }: { judge: Judge | null }) {
  if (!judge) {
    return (
      <div className="rounded bg-zinc-900 p-2.5">
        <div className="text-[9px] uppercase tracking-wider text-zinc-500">
          Judge · no LLM judge for this step
        </div>
      </div>
    );
  }
  return (
    <div className="rounded bg-zinc-900 p-2.5">
      <div className="flex items-center justify-between">
        <div className="text-[9px] uppercase tracking-wider text-zinc-500">Judge</div>
        <div className="text-[11px] font-semibold text-green-400">
          {judge.score?.toFixed(1) ?? "—"}
          <span className="text-[9px] text-zinc-500">/10</span>
        </div>
      </div>
      {Object.keys(judge.criteria).length > 0 && (
        <div className="mt-1.5 grid grid-cols-2 gap-x-2 gap-y-0.5 text-[9px] text-zinc-400">
          {Object.entries(judge.criteria).map(([key, value]) => (
            <div key={key} className="flex justify-between">
              <span>{key}</span>
              <span>{value}</span>
            </div>
          ))}
        </div>
      )}
      {judge.rationale && (
        <p className="mt-2 text-[10px] leading-relaxed text-zinc-400">
          {judge.rationale}
        </p>
      )}
    </div>
  );
}
