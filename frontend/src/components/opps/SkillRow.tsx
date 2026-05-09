import type { PerRunSummary, Step } from "../../api/types";

interface Props {
  step: Step;
  isSelected: boolean;
  priorRunStep: Step | null;
  onClick: () => void;
  /**
   * Per-run history for THIS skill across the most recent runs (newest
   * first), built by SkillList from MultiRunSummary.per_run. Optional —
   * row degrades to no sparkline when absent or when this skill only
   * has one scored run (sparkline of one point isn't a trend).
   */
  runHistory?: PerRunSummary[];
  currentRunId?: string;
}

export function SkillRow({
  step,
  isSelected,
  priorRunStep,
  onClick,
  runHistory,
  currentRunId,
}: Props) {
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
      {step.has_judge && runHistory && runHistory.length > 1 && (
        <RunScoreSparkline
          skillName={step.skill_name}
          runs={runHistory}
          currentRunId={currentRunId}
        />
      )}
    </button>
  );
}

function RunScoreSparkline({
  skillName,
  runs,
  currentRunId,
}: {
  skillName: string;
  runs: PerRunSummary[];
  currentRunId?: string;
}) {
  // Only render when there are at least 2 runs that produced a score
  // for this skill — otherwise the "trend" is a single point. Renders
  // newest-first to match the run-history strip in the header.
  const points = runs.map((r) => ({
    runId: r.run_id,
    score: r.skill_scores[skillName] ?? null,
  }));
  const scoredCount = points.filter((p) => p.score !== null).length;
  if (scoredCount < 2) return null;
  return (
    <span
      className="ml-1 inline-flex shrink-0 items-center gap-0.5"
      title={pointsTooltip(skillName, points)}
      aria-label={`${skillName} score across recent runs`}
    >
      {points.map((p) => (
        <span
          key={p.runId}
          className={
            "h-1.5 w-1.5 rounded-full " +
            sparklineTone(p.score) +
            (p.runId === currentRunId ? " ring-1 ring-foreground/60" : "")
          }
        />
      ))}
    </span>
  );
}

function pointsTooltip(
  skillName: string,
  points: { runId: string; score: number | null }[],
): string {
  const lines = [`${skillName} across recent runs (newest first):`];
  for (const p of points) {
    const score = p.score === null ? "no score" : `${Math.round(p.score)}/100`;
    lines.push(`  ${p.runId} — ${score}`);
  }
  return lines.join("\n");
}

function sparklineTone(score: number | null): string {
  if (score === null) return "bg-muted-foreground/30";
  if (score >= 80) return "bg-emerald-500/80";
  if (score >= 60) return "bg-amber-500/80";
  return "bg-rose-500/80";
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

