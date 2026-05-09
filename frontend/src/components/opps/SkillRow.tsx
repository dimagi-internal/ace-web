import type { Step } from "../../api/types";

interface Props {
  step: Step;
  isSelected: boolean;
  priorRunStep: Step | null;
  onClick: () => void;
}

export function SkillRow({ step, isSelected, priorRunStep, onClick }: Props) {
  // Use the server-normalized 0-100 score everywhere so width, label, and
  // delta are on one consistent scale. Falls back to score for old API
  // payloads that haven't deployed score_pct yet.
  const judgeScorePct = step.judge?.score_pct ?? step.judge?.score ?? null;
  const priorScorePct =
    priorRunStep?.judge?.score_pct ?? priorRunStep?.judge?.score ?? null;
  const delta =
    judgeScorePct !== null && priorScorePct !== null
      ? judgeScorePct - priorScorePct
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
      <span
        className="w-[160px] shrink-0 truncate font-semibold text-foreground"
        title={step.skill_name}
      >
        {step.display_name || step.skill_name}
      </span>
      {step.has_judge ? (
        <>
          <JudgeBar scorePct={judgeScorePct} />
          <span className="w-[44px] shrink-0 text-[11px] text-green-400">
            {judgeScorePct === null ? "—" : `${Math.round(judgeScorePct)}`}
          </span>
          <span className={`w-[48px] shrink-0 text-[10px] ${deltaTone(delta)}`}>
            {formatDelta(delta)}
          </span>
        </>
      ) : (
        <>
          {/* Preserve the judge-column widths so skill names line up across
              rows, but drop the "no judge" label — it was internal-speak
              leaking into the UI. */}
          <span className="w-[54px] shrink-0" />
          <span className="w-[44px] shrink-0" />
          <span className="w-[48px] shrink-0" />
        </>
      )}
      <span
        className="flex-1 truncate text-[11px] text-muted-foreground"
        title={step.preview_text}
      >
        {step.preview_text}
      </span>
    </button>
  );
}

function StatusDot({ status }: { status: string }) {
  const color = statusColor(status);
  const label = statusLabel(status);
  return (
    <span
      className={`w-3 shrink-0 text-center text-[11px] ${color}`}
      // Pair the color-only glyph with a tooltip word so the status is
      // legible to screen readers and color-blind users; AT users can't
      // distinguish red ✗ from amber ⚠ on color alone.
      title={label}
      aria-label={label}
      role="img"
    >
      {statusGlyph(status)}
    </span>
  );
}

function statusGlyph(status: string): string {
  if (status === "complete") return "✓";
  if (status === "running") return "▶";
  if (status === "judge-fail") return "✗";
  if (status === "error") return "✗";
  if (status === "skipped") return "—";
  return "○";
}

function statusLabel(status: string): string {
  if (status === "complete") return "complete";
  if (status === "running") return "running";
  if (status === "judge-fail") return "judge failed";
  if (status === "error") return "error";
  if (status === "skipped") return "skipped";
  if (status === "pending") return "pending";
  return status;
}

function statusColor(status: string): string {
  if (status === "complete") return "text-green-500";
  if (status === "running") return "text-blue-400";
  if (status === "judge-fail" || status === "error") return "text-red-500";
  return "text-muted-foreground";
}

function JudgeBar({ scorePct }: { scorePct: number | null }) {
  const pct = scorePct !== null ? Math.min(100, Math.max(0, scorePct)) : 0;
  const tone =
    scorePct === null ? "bg-muted"
    : scorePct >= 80 ? "bg-green-500"
    : scorePct >= 60 ? "bg-amber-500"
    : "bg-red-500";
  return (
    <span className="relative block h-1.5 w-[54px] shrink-0 overflow-hidden rounded bg-card">
      <span className={`absolute inset-y-0 left-0 ${tone}`} style={{ width: `${pct}%` }} />
    </span>
  );
}

function formatDelta(delta: number | null): string {
  if (delta === null) return "";
  const rounded = Math.round(delta);
  if (rounded === 0) return "±0";
  const arrow = rounded > 0 ? "↑" : "↓";
  const sign = rounded > 0 ? "+" : "";
  return `${arrow} ${sign}${rounded}`;
}

function deltaTone(delta: number | null): string {
  if (delta === null) return "text-muted-foreground";
  if (delta > 0.5) return "text-green-400";
  if (delta < -0.5) return "text-red-400";
  return "text-muted-foreground";
}

