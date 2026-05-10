import type { PerRunSummary } from "../../api/types";

interface Props {
  /** Per-run aggregates, newest-first (matches the API's per_run order). */
  runs: PerRunSummary[];
  selectedRunId: string | null;
  onChange: (runId: string) => void;
}

/**
 * Compact strip of dots beside the run selector — one dot per run, colored
 * by mean opp-eval score so the "did the latest run improve over the
 * prior one?" question is answerable visually without opening the Diff
 * tab. Newest run on the LEFT (matches the dropdown's newest-first order).
 *
 * Click a dot to switch to that run. Hidden when the opp has fewer than
 * 2 runs — a single dot adds nothing.
 */
export function RunHistoryStrip({ runs, selectedRunId, onChange }: Props) {
  if (runs.length < 2) return null;

  return (
    <span
      className="inline-flex items-center gap-0.5"
      role="group"
      aria-label="Run history — click a dot to switch"
    >
      {runs.map((r) => {
        const selected = r.run_id === selectedRunId;
        const tone = scoreTone(r.mean_score);
        return (
          <button
            key={r.run_id}
            type="button"
            onClick={() => onChange(r.run_id)}
            aria-current={selected ? "true" : undefined}
            title={runTooltip(r)}
            className={
              "h-2 w-2 rounded-full transition " +
              tone +
              (selected
                ? " ring-2 ring-foreground/60 ring-offset-1 ring-offset-background"
                : " hover:ring-2 hover:ring-foreground/30 hover:ring-offset-1 hover:ring-offset-background")
            }
          />
        );
      })}
    </span>
  );
}

// Score-coded color. We could also branch on a "passed" field, but
// MultiRunSummary doesn't surface a per-run pass/fail directly — only
// mean_score. The tone is a visual indicator, not a verdict; tooltip
// carries the precise info.
function scoreTone(meanScore: number | null): string {
  if (meanScore === null) return "bg-muted-foreground/30";
  if (meanScore >= 80) return "bg-emerald-500/80";
  if (meanScore >= 60) return "bg-amber-500/80";
  return "bg-rose-500/80";
}

function runTooltip(r: PerRunSummary): string {
  const parts: string[] = [`Run ${r.run_id}`];
  if (r.mean_score !== null) {
    parts.push(`mean ${Math.round(r.mean_score)}/100`);
  } else {
    parts.push("no scored skills yet");
  }
  parts.push(`${r.complete_count}/${r.total_count} complete`);
  if (r.last_actor_at) parts.push(new Date(r.last_actor_at).toLocaleString());
  return parts.join(" · ");
}
