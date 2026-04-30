import type { OppSnapshot, Step } from "../../api/types";

interface Props {
  a: OppSnapshot;
  b: OppSnapshot;
}

export function CompareTable({ a, b }: Props) {
  const allSkills = new Set<string>();
  [...a.current_run.steps, ...b.current_run.steps].forEach((s) =>
    allSkills.add(s.skill_name),
  );
  const sorted = [...allSkills].sort((x, y) => {
    const ax = a.current_run.steps.find((s) => s.skill_name === x)?.ordinal ?? 999;
    const ay = a.current_run.steps.find((s) => s.skill_name === y)?.ordinal ?? 999;
    const bx = b.current_run.steps.find((s) => s.skill_name === x)?.ordinal ?? 999;
    const by = b.current_run.steps.find((s) => s.skill_name === y)?.ordinal ?? 999;
    return Math.min(ax, bx) - Math.min(ay, by);
  });

  return (
    <div className="grid grid-cols-[1fr_auto_1fr] gap-3 p-4">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {a.opp.display_name || a.opp.slug}
      </div>
      <div className="w-24" />
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {b.opp.display_name || b.opp.slug}
      </div>

      {sorted.map((name) => {
        const aStep = a.current_run.steps.find((s) => s.skill_name === name) ?? null;
        const bStep = b.current_run.steps.find((s) => s.skill_name === name) ?? null;
        const delta = computeDelta(aStep, bStep);
        return (
          <SideBySideRow
            key={name}
            skillName={name}
            aStep={aStep}
            bStep={bStep}
            delta={delta}
          />
        );
      })}
    </div>
  );
}

function computeDelta(a: Step | null, b: Step | null): number | null {
  if (a?.judge?.score == null || b?.judge?.score == null) return null;
  return b.judge.score - a.judge.score;
}

function SideBySideRow({
  skillName,
  aStep,
  bStep,
  delta,
}: {
  skillName: string;
  aStep: Step | null;
  bStep: Step | null;
  delta: number | null;
}) {
  return (
    <>
      <div className="rounded border border-border bg-card p-2 text-xs">
        {aStep ? (
          <StepCell step={aStep} />
        ) : (
          <span className="text-muted-foreground">— not in opp</span>
        )}
      </div>
      <div className="flex w-24 items-center justify-center text-[10px]">
        <div className="text-center">
          <div className="font-mono text-foreground">{skillName}</div>
          <div className={deltaTone(delta)}>{formatDelta(delta)}</div>
        </div>
      </div>
      <div className="rounded border border-border bg-card p-2 text-xs">
        {bStep ? (
          <StepCell step={bStep} />
        ) : (
          <span className="text-muted-foreground">— not in opp</span>
        )}
      </div>
    </>
  );
}

function StepCell({ step }: { step: Step }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-muted-foreground">{step.status}</span>
        {step.judge?.score != null && (
          <span className="text-[11px] font-semibold text-emerald-300">
            {formatScore(step.judge.score)}
          </span>
        )}
      </div>
      {gateBadge(step) && (
        <div className="mt-1 text-[10px] font-medium">{gateBadge(step)}</div>
      )}
      {step.preview_text && (
        <div className="mt-1 line-clamp-2 text-[10px] text-muted-foreground">
          {step.preview_text}
        </div>
      )}
    </div>
  );
}

function gateBadge(step: Step): string | null {
  if (!step.gates || step.gates.length === 0) return null;
  const last = step.gates[step.gates.length - 1];
  if (last.decision === "pending") return "● no decision";
  if (last.decision === "approved") return "✓ approved";
  if (last.decision === "rejected") return "✕ rejected";
  return null;
}

function formatScore(s: number): string {
  // Plugin scores are usually 0-100; some are 0-10. Branch on value.
  return s > 10 ? `${s.toFixed(0)}/100` : `${s.toFixed(1)}/10`;
}

function formatDelta(d: number | null): string {
  if (d === null) return "—";
  if (Math.abs(d) < 0.05) return "= 0";
  return `${d > 0 ? "↑ +" : "↓ "}${d.toFixed(1)}`;
}

function deltaTone(d: number | null): string {
  if (d === null) return "text-muted-foreground";
  if (d > 0.05) return "text-emerald-400";
  if (d < -0.05) return "text-red-400";
  return "text-muted-foreground";
}
