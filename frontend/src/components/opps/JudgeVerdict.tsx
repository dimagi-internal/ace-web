import type { Judge, JudgeCriterionValue } from "../../api/types";

// Judge verdicts emit criteria in two shapes:
//   - legacy: Record<string, number>            (just a score)
//   - plugin: Record<string, {score, weight, ...}>
// Returning the value verbatim through JSX crashes (React error #31).
// extractScore picks a number out of either; extractMeta surfaces the
// optional strength/weakness for object-shaped values.
function extractScore(value: JudgeCriterionValue): number | null {
  if (typeof value === "number") return value;
  if (value && typeof value === "object" && typeof value.score === "number") {
    return value.score;
  }
  return null;
}

function extractMeta(value: JudgeCriterionValue): { strength: string; weakness: string } {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const strength = typeof value.strength === "string" ? value.strength : "";
    const weakness = typeof value.weakness === "string" ? value.weakness : "";
    return { strength, weakness };
  }
  return { strength: "", weakness: "" };
}

export function JudgeVerdict({ judge }: { judge: Judge | null }) {
  if (!judge) {
    return (
      <div className="rounded bg-card p-2.5">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
          Judge · no LLM judge for this step
        </div>
      </div>
    );
  }
  const scoreShown = judge.score_pct ?? judge.score;
  const scoreLabel =
    scoreShown === null
      ? "—"
      : judge.score_pct !== null
        ? `${Math.round(judge.score_pct)}/100`
        : `${scoreShown.toFixed(1)}/10`;
  const entries = Object.entries(judge.criteria);
  return (
    <div className="rounded bg-card p-2.5">
      <div className="flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Judge</div>
        <div className="text-xs font-semibold text-green-400">{scoreLabel}</div>
      </div>
      {entries.length > 0 && (
        <div className="mt-1.5 grid grid-cols-2 gap-x-2 gap-y-1 text-[11px]">
          {entries.map(([key, value]) => {
            const score = extractScore(value);
            const { strength, weakness } = extractMeta(value);
            return (
              <div key={key} className="flex flex-col gap-0.5">
                <div className="flex justify-between gap-2 text-muted-foreground">
                  <span className="truncate" title={key}>{key}</span>
                  <span className="shrink-0 text-foreground">
                    {score === null ? "—" : score}
                  </span>
                </div>
                {(strength || weakness) && (
                  <div className="text-[10px] text-muted-foreground/80">
                    {strength && <div className="truncate" title={strength}>+ {strength}</div>}
                    {weakness && <div className="truncate" title={weakness}>− {weakness}</div>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {judge.rationale && (
        <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
          {judge.rationale}
        </p>
      )}
    </div>
  );
}
