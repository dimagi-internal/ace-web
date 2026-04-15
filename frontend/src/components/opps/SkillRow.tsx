import type { Step } from "../../api/types";

interface Props {
  step: Step;
  isSelected: boolean;
  priorRunStep: Step | null;
  onClick: () => void;
}

export function SkillRow({ step, isSelected, priorRunStep, onClick }: Props) {
  const judgeScore = step.judge?.score ?? null;
  const priorScore = priorRunStep?.judge?.score ?? null;
  const delta =
    judgeScore !== null && priorScore !== null
      ? judgeScore - priorScore
      : null;

  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-3 rounded px-2 py-2 text-left text-xs ${
        isSelected
          ? "border border-primary bg-primary/10"
          : "border border-transparent bg-card hover:bg-accent"
      }`}
    >
      <StatusDot status={step.status} />
      <span className="w-[140px] shrink-0 font-semibold text-foreground">
        {step.skill_name}
      </span>
      {step.has_judge ? (
        <>
          <JudgeBar score={judgeScore} />
          <span className="w-[32px] shrink-0 text-[11px] text-green-400">
            {judgeScore?.toFixed(1) ?? "—"}
          </span>
          <span className={`w-[48px] shrink-0 text-[10px] ${deltaTone(delta)}`}>
            {formatDelta(delta)}
          </span>
        </>
      ) : (
        <>
          <span className="w-[54px] shrink-0 text-[10px] text-muted-foreground">no judge</span>
          <span className="w-[32px] shrink-0" />
          <span className="w-[48px] shrink-0" />
        </>
      )}
      <span className="flex-1 truncate text-[11px] text-muted-foreground">
        {step.preview_text}
      </span>
    </button>
  );
}

function StatusDot({ status }: { status: string }) {
  const color = statusColor(status);
  return <span className={`w-3 shrink-0 text-center text-[11px] ${color}`}>{statusGlyph(status)}</span>;
}

function statusGlyph(status: string): string {
  if (status === "complete") return "✓";
  if (status === "running") return "▶";
  if (status === "judge-fail") return "✗";
  if (status === "gate-pending" || status === "gate-rejected") return "⚠";
  if (status === "error") return "✗";
  if (status === "skipped") return "—";
  return "○";
}

function statusColor(status: string): string {
  if (status === "complete") return "text-green-500";
  if (status === "running") return "text-blue-400";
  if (status === "judge-fail" || status === "error") return "text-red-500";
  if (status === "gate-pending" || status === "gate-rejected") return "text-amber-500";
  return "text-muted-foreground";
}

function JudgeBar({ score }: { score: number | null }) {
  const pct = score !== null ? Math.min(100, Math.max(0, score * 10)) : 0;
  const tone =
    score === null ? "bg-muted"
    : score >= 8 ? "bg-green-500"
    : score >= 6 ? "bg-amber-500"
    : "bg-red-500";
  return (
    <span className="relative block h-1.5 w-[54px] shrink-0 overflow-hidden rounded bg-card">
      <span className={`absolute inset-y-0 left-0 ${tone}`} style={{ width: `${pct}%` }} />
    </span>
  );
}

function formatDelta(delta: number | null): string {
  if (delta === null) return "";
  const rounded = Math.round(delta * 10) / 10;
  if (rounded === 0) return "= 0";
  const arrow = rounded > 0 ? "↑" : "↓";
  const sign = rounded > 0 ? "+" : "";
  return `${arrow} ${sign}${rounded.toFixed(1)}`;
}

function deltaTone(delta: number | null): string {
  if (delta === null) return "text-muted-foreground";
  if (delta > 0.05) return "text-green-400";
  if (delta < -0.05) return "text-red-400";
  return "text-muted-foreground";
}

