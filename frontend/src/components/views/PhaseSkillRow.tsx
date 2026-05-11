import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronRight, ExternalLink } from "lucide-react";

import type { Step } from "@/api/types";
import { cn } from "@/lib/utils";

import { EvalSection, ProducerSection, QASection } from "./phase-skill/sections";

interface Props {
  step: Step;
  oppSlug: string;
  runId: string;
}

/**
 * Collapsible skill row for the Phases view.
 *
 * Collapsed shows: status dot · display name · QA chip · eval bar +
 * score + delta · preview · chevron. The QA and eval indicators always
 * occupy the same column so rows scan vertically.
 *
 * Expanded reveals a drawer with three explicitly-labeled sections —
 * **Producer**, **QA**, **Eval** — so the user always knows which skill
 * generated which output. When a section's data is absent (no QA
 * defined, eval skipped because QA gated, etc.) we render a labeled stub
 * rather than hiding it, so the absence is itself visible.
 */
export function PhaseSkillRow({ step, oppSlug, runId }: Props) {
  const [open, setOpen] = useState(false);
  const { workspaceSlug = "" } = useParams<{ workspaceSlug?: string }>();
  const judgeScorePct = step.judge?.score_pct ?? step.judge?.score ?? null;

  return (
    <div className={cn("rounded border", open ? "border-border bg-card" : "border-transparent")}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={cn(
          "flex w-full items-center gap-3 rounded px-2 py-2 text-left text-xs",
          step.status === "qa-failed" && !open
            ? "border border-rose-500/30 bg-rose-500/5"
            : open
              ? ""
              : "bg-card hover:bg-accent",
        )}
      >
        <StatusDot status={step.status} />
        <span
          className="w-[170px] shrink-0 truncate font-semibold text-foreground"
          title={step.skill_name}
        >
          {step.display_name || step.skill_name}
        </span>
        <QAChip step={step} />
        <EvalBar scorePct={judgeScorePct} hasJudge={step.has_judge} qaFailed={step.qa_result?.verdict === "fail"} />
        <span
          className="flex-1 truncate text-[11px] text-muted-foreground"
          title={step.preview_text}
        >
          {step.preview_text}
        </span>
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            open ? "rotate-90 text-foreground" : "",
          )}
        />
      </button>
      {open && (
        <div className="animate-in fade-in slide-in-from-top-1 duration-150 border-t border-border px-3 py-3">
          <ProducerSection step={step} />
          <QASection step={step} />
          <EvalSection step={step} />
          <div className="mt-3 flex items-center gap-3 border-t border-border pt-2 text-[11px]">
            <Link
              to={`/w/${workspaceSlug}/opps/${oppSlug}/runs/${runId}/steps/${step.skill_name}?view=workbench`}
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
            >
              Open in Workbench <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Collapsed-row pieces ────────────────────────────────────────────

function StatusDot({ status }: { status: string }) {
  const { glyph, color, label } = statusVisual(status);
  return (
    <span
      className={cn("w-3 shrink-0 text-center text-[11px]", color)}
      title={label}
      aria-label={label}
      role="img"
    >
      {glyph}
    </span>
  );
}

function statusVisual(status: string): { glyph: string; color: string; label: string } {
  if (status === "complete") return { glyph: "✓", color: "text-green-500", label: "complete" };
  if (status === "running") return { glyph: "▶", color: "text-blue-400", label: "running" };
  if (status === "qa-failed")
    return { glyph: "✗", color: "text-rose-500", label: "QA failed" };
  if (status === "judge-fail" || status === "error")
    return { glyph: "✗", color: "text-rose-500", label: "failed" };
  if (status === "skipped") return { glyph: "—", color: "text-muted-foreground", label: "skipped" };
  return { glyph: "○", color: "text-muted-foreground", label: status };
}

function QAChip({ step }: { step: Step }) {
  const qa = step.qa_result;
  if (!qa) {
    return (
      <span
        className="inline-flex h-[18px] shrink-0 items-center gap-1 rounded border border-border/60 bg-transparent px-1.5 text-[10px] font-semibold text-muted-foreground/60"
        title="No QA defined for this skill yet"
      >
        <span>QA</span>
        <span>—</span>
      </span>
    );
  }
  if (qa.verdict === "pass") {
    return (
      <span
        className="inline-flex h-[18px] shrink-0 items-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 text-[10px] font-semibold text-emerald-500"
        title={`QA passed (${qa.stats.checks_passed}/${qa.stats.checks_run} checks)`}
      >
        <span>QA</span>
        <span>✓</span>
      </span>
    );
  }
  if (qa.verdict === "fail") {
    return (
      <span
        className="inline-flex h-[18px] shrink-0 items-center gap-1 rounded border border-rose-500/40 bg-rose-500/10 px-1.5 text-[10px] font-semibold text-rose-500"
        title={`QA failed (${qa.stats.checks_failed} of ${qa.stats.checks_run} checks)`}
      >
        <span>QA</span>
        <span>✗</span>
        <span className="ml-0.5 font-normal opacity-90">
          {qa.stats.checks_failed}/{qa.stats.checks_run}
        </span>
      </span>
    );
  }
  return (
    <span className="inline-flex h-[18px] shrink-0 items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 text-[10px] font-semibold text-amber-500">
      <span>QA</span>
      <span>⏳</span>
    </span>
  );
}

function EvalBar({
  scorePct,
  hasJudge,
  qaFailed,
}: {
  scorePct: number | null;
  hasJudge: boolean;
  qaFailed: boolean;
}) {
  if (qaFailed) {
    return (
      <span className="flex shrink-0 items-center gap-2">
        <span className="block h-1.5 w-[54px] rounded bg-card opacity-30" />
        <span className="w-[44px] text-right text-[11px] text-muted-foreground/60">—</span>
        <span className="w-[78px] text-[10px] text-muted-foreground/60">eval skipped</span>
      </span>
    );
  }
  if (!hasJudge) {
    return (
      <span className="flex shrink-0 items-center gap-2">
        <span className="block h-1.5 w-[54px] rounded bg-card opacity-25" />
        <span className="w-[44px] text-right text-[11px] text-muted-foreground/60">—</span>
        <span className="w-[78px] text-[10px] text-muted-foreground/60">no eval</span>
      </span>
    );
  }
  const pct = scorePct !== null ? Math.min(100, Math.max(0, scorePct)) : 0;
  const tone =
    scorePct === null
      ? "bg-muted"
      : scorePct >= 80
        ? "bg-green-500"
        : scorePct >= 60
          ? "bg-amber-500"
          : "bg-red-500";
  const scoreColor =
    scorePct === null
      ? "text-muted-foreground"
      : scorePct >= 80
        ? "text-green-400"
        : scorePct >= 60
          ? "text-amber-400"
          : "text-red-400";
  return (
    <span className="flex shrink-0 items-center gap-2">
      <span className="relative block h-1.5 w-[54px] overflow-hidden rounded bg-card">
        <span className={cn("absolute inset-y-0 left-0", tone)} style={{ width: `${pct}%` }} />
      </span>
      <span className={cn("w-[44px] text-right text-[11px] tabular-nums", scoreColor)}>
        {scorePct === null ? "—" : `${Math.round(scorePct)}`}
      </span>
      <span className="w-[78px] text-[10px] text-muted-foreground">/100 eval</span>
    </span>
  );
}
