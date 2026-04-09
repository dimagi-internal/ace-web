import type { Run, Step } from "../../api/types";

interface Props {
  fromRun: Run;
  toRun: Run;
}

export function CompareTable({ fromRun, toRun }: Props) {
  const allSkills = new Set<string>();
  [...fromRun.steps, ...toRun.steps].forEach((s) => allSkills.add(s.skill_name));
  const sorted = [...allSkills].sort((a, b) => {
    const fa = fromRun.steps.find((s) => s.skill_name === a)?.ordinal ?? 999;
    const fb = fromRun.steps.find((s) => s.skill_name === b)?.ordinal ?? 999;
    const ta = toRun.steps.find((s) => s.skill_name === a)?.ordinal ?? 999;
    const tb = toRun.steps.find((s) => s.skill_name === b)?.ordinal ?? 999;
    return Math.min(fa, ta) - Math.min(fb, tb);
  });

  return (
    <div className="grid grid-cols-[1fr_auto_1fr] gap-3 p-4">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">
        Run {fromRun.run_id}
      </div>
      <div className="w-20" />
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">
        Run {toRun.run_id}
      </div>

      {sorted.map((name) => {
        const fromStep = fromRun.steps.find((s) => s.skill_name === name) ?? null;
        const toStep = toRun.steps.find((s) => s.skill_name === name) ?? null;
        const delta = computeDelta(fromStep, toStep);
        return (
          <SideBySideRow key={name} fromStep={fromStep} toStep={toStep} delta={delta} />
        );
      })}
    </div>
  );
}

function computeDelta(a: Step | null, b: Step | null): number | null {
  if (!a?.judge?.score || !b?.judge?.score) return null;
  return b.judge.score - a.judge.score;
}

function SideBySideRow({
  fromStep,
  toStep,
  delta,
}: {
  fromStep: Step | null;
  toStep: Step | null;
  delta: number | null;
}) {
  const skillName = toStep?.skill_name ?? fromStep?.skill_name ?? "—";
  return (
    <>
      <div className="rounded bg-zinc-900 p-2 text-xs">
        {fromStep ? <StepCell step={fromStep} /> : <span className="text-zinc-600">— not in run</span>}
      </div>
      <div className="flex w-20 items-center justify-center text-[10px]">
        <div className="text-center">
          <div className="font-mono text-zinc-100">{skillName}</div>
          <div className={deltaTone(delta)}>{formatDelta(delta)}</div>
        </div>
      </div>
      <div className="rounded bg-zinc-900 p-2 text-xs">
        {toStep ? <StepCell step={toStep} /> : <span className="text-zinc-600">— not in run</span>}
      </div>
    </>
  );
}

function StepCell({ step }: { step: Step }) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-zinc-400">{step.status}</span>
        {step.judge?.score !== undefined && step.judge?.score !== null && (
          <span className="text-[11px] font-semibold text-green-400">
            {step.judge.score.toFixed(1)}
          </span>
        )}
      </div>
      <div className="mt-1 truncate text-[10px] text-zinc-500">{step.preview_text}</div>
    </div>
  );
}

function formatDelta(d: number | null): string {
  if (d === null) return "—";
  if (Math.abs(d) < 0.05) return "= 0";
  return `${d > 0 ? "↑ +" : "↓ "}${d.toFixed(1)}`;
}

function deltaTone(d: number | null): string {
  if (d === null) return "text-zinc-600";
  if (d > 0.05) return "text-green-400";
  if (d < -0.05) return "text-red-400";
  return "text-zinc-500";
}
