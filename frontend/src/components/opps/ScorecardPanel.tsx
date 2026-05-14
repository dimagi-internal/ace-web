/**
 * Run-level opp-eval scorecard chip + dialog for the Workbench header.
 *
 * The ACE plugin's umbrella ``opp-eval`` skill aggregates every per-skill
 * ``verdicts/*.yaml`` into a single run scorecard and emits:
 *
 *   - ``verdicts/opp-eval-{deep,monitor}.yaml`` — machine-readable score
 *   - ``scorecards/YYYY-MM-DD-opp-eval-*.md``  — human-readable narrative
 *   - ``scorecards/trend.md``                  — rolling trend across runs
 *
 * This panel surfaces all three. Collapsed it's a score chip; expanded it
 * shows dimensions, full scorecard body, and the trend file.
 */
import { useEffect, useState } from "react";

import { getScorecard } from "../../api/opps";
import type { Scorecard } from "../../api/types.ws";
import { MarkdownRenderer } from "../MarkdownRenderer";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/dialog";

interface Props {
  workspaceSlug: string;
  slug: string;
}

function verdictColor(scorePct: number | null | undefined, passed: boolean | null) {
  if (passed === false) return "text-destructive";
  if (scorePct === null || scorePct === undefined) return "text-muted-foreground";
  if (scorePct >= 80) return "text-green-500";
  if (scorePct >= 60) return "text-amber-500";
  return "text-destructive";
}

function verdictLabel(passed: boolean | null): string {
  if (passed === true) return "pass";
  if (passed === false) return "fail";
  return "—";
}

export function ScorecardPanel({ workspaceSlug, slug }: Props) {
  const [data, setData] = useState<Scorecard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setData(null);
    getScorecard(workspaceSlug, slug)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : String(err);
          setError(msg);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  // Nothing to show yet — scorecards are opt-in; don't distract the header
  // on opps that haven't run opp-eval.
  if (error || !data || !data.latest_verdict) {
    return null;
  }

  const judge = data.latest_verdict;
  const scorePct = judge.score_pct ?? (judge.score === null ? null : judge.score > 10 ? judge.score : judge.score * 10);
  const variant = data.latest_verdict_variant ?? "";
  const scoreLabel = scorePct === null ? "—" : `${Math.round(scorePct)}/100`;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded bg-muted px-2 py-0.5 text-xs hover:bg-muted/70"
        title="Run-level opp-eval scorecard"
      >
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
          opp-eval
          {variant && ` · ${variant}`}
        </span>
        <span className={`font-semibold ${verdictColor(scorePct, judge.passed)}`}>
          {scoreLabel}
        </span>
        <span className="text-[10px] text-muted-foreground">
          {verdictLabel(judge.passed)}
        </span>
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              Run scorecard
              {variant && (
                <span className="ml-2 text-xs font-normal text-muted-foreground">
                  opp-eval · {variant}
                </span>
              )}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="flex items-baseline gap-4 rounded border border-border bg-card p-3">
              <div className={`text-3xl font-semibold ${verdictColor(scorePct, judge.passed)}`}>
                {scoreLabel}
              </div>
              <div className="text-sm text-muted-foreground">
                {verdictLabel(judge.passed)}
                {judge.evaluated_at && (
                  <span className="ml-2 text-xs opacity-70">
                    · {new Date(judge.evaluated_at).toLocaleString()}
                  </span>
                )}
              </div>
            </div>

            {Object.keys(judge.criteria).length > 0 && (
              <div>
                <div className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">
                  Dimensions
                </div>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  {Object.entries(judge.criteria).map(([key, value]) => (
                    <DimensionRow key={key} name={key} value={value} />
                  ))}
                </div>
              </div>
            )}

            {judge.rationale && (
              <div>
                <div className="mb-1 text-xs uppercase tracking-wider text-muted-foreground">
                  Summary
                </div>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {judge.rationale}
                </p>
              </div>
            )}

            {data.latest_scorecard_body && (
              <div>
                <div className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">
                  Scorecard{" "}
                  {data.latest_scorecard_path && (
                    <span className="normal-case opacity-70">
                      · {data.latest_scorecard_path}
                    </span>
                  )}
                </div>
                <div className="rounded border border-border bg-background p-3">
                  <MarkdownRenderer content={data.latest_scorecard_body} />
                </div>
              </div>
            )}

            {data.trend_body && (
              <div>
                <div className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">
                  Trend
                </div>
                <div className="rounded border border-border bg-background p-3">
                  <MarkdownRenderer content={data.trend_body} />
                </div>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

function DimensionRow({
  name,
  value,
}: {
  name: string;
  value: number | Record<string, unknown>;
}) {
  // The plugin emits dimensions as either {score: number, ...} objects or
  // plain numbers; handle both.
  let score: number | null = null;
  let strength = "";
  let weakness = "";
  if (typeof value === "number") {
    score = value;
  } else if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    if (typeof obj.score === "number") score = obj.score;
    if (typeof obj.strength === "string") strength = obj.strength;
    if (typeof obj.weakness === "string") weakness = obj.weakness;
  }
  // Dimensions are usually 0-10 — promote to a 0-100 scale just for color
  // tone; keep the original value in the label so the user sees the
  // dimension as the plugin emitted it.
  const scorePct = score === null ? null : score > 10 ? score : score * 10;
  return (
    <div className="flex flex-col gap-0.5 rounded border border-border bg-card p-2">
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-medium">{name}</span>
        <span
          className={`text-sm font-semibold ${verdictColor(scorePct, null)}`}
        >
          {score === null ? "—" : score}
        </span>
      </div>
      {(strength || weakness) && (
        <div className="mt-1 space-y-0.5 text-[10px] text-muted-foreground">
          {strength && <div>+ {strength}</div>}
          {weakness && <div>− {weakness}</div>}
        </div>
      )}
    </div>
  );
}
