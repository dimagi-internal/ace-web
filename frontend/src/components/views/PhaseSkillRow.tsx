import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronRight, ExternalLink } from "lucide-react";

import type { Decision, Step } from "@/api/types.ws";
import { Glossed } from "@/components/glossary/Glossed";
import { cn } from "@/lib/utils";

import {
  DecisionsSection,
  EvalSection,
  isFinished,
  ProducerSection,
  QASection,
} from "./phase-skill/sections";

interface Props {
  step: Step;
  oppSlug: string;
  runId: string;
  /** Replay: the cursor is on this step, so open the drawer without a click —
   *  the Producer / QA / Eval sections are the thing worth watching land.
   *  Only rows this opened are auto-closed again; a row someone opened by
   *  hand stays open as the cursor moves on. */
  autoOpen?: boolean;
  /** Decisions this skill recorded (already filtered to the replay cursor). */
  decisions?: readonly Decision[];
  /** The run is still going: a finished producer's eval may yet land, so a
   *  missing score is pending, not missing. */
  runLive?: boolean;
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
export function PhaseSkillRow({
  step,
  oppSlug,
  runId,
  autoOpen = false,
  decisions = [],
  runLive = false,
}: Props) {
  const finished = isFinished(step.status) && !runLive;
  const [open, setOpen] = useState(false);
  const openedByReplay = useRef(false);

  useEffect(() => {
    if (autoOpen) {
      setOpen(true);
      openedByReplay.current = true;
    } else if (openedByReplay.current) {
      setOpen(false);
      openedByReplay.current = false;
    }
  }, [autoOpen]);
  const { workspaceSlug = "" } = useParams<{ workspaceSlug?: string }>();
  const judgeScorePct = step.judge?.score_pct ?? step.judge?.score ?? null;

  return (
    <div className={cn("rounded border", open ? "border-border bg-card" : "border-transparent")}>
      <button
        type="button"
        onClick={() => {
          // A hand-driven toggle takes ownership: the cursor moving on will
          // no longer close this row.
          openedByReplay.current = false;
          setOpen((v) => !v);
        }}
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
          <Glossed text={step.display_name || step.skill_name} />
        </span>
        <QAChip step={step} finished={finished} />
        <EvalChip
          scorePct={judgeScorePct}
          hasJudge={step.has_judge}
          qaFailed={step.qa_result?.verdict === "fail"}
          finished={finished}
        />
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
          {decisions.length > 0 && <DecisionsSection decisions={decisions} />}
          <QASection step={step} />
          <EvalSection step={step} finished={finished} />
          <div className="mt-3 flex items-center gap-3 border-t border-border pt-2 text-[11px]">
            <Link
              to={`/w/${workspaceSlug}/opps/${encodeURIComponent(oppSlug)}/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(step.skill_name)}?view=workbench`}
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

function QAChip({ step, finished }: { step: Step; finished: boolean }) {
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
  // Neither pass nor fail. On a step that has finished that is a verdict
  // ("incomplete", "warn"), not something still running — say which.
  if (finished) {
    return (
      <span
        className="inline-flex h-[18px] shrink-0 items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 text-[10px] font-semibold text-amber-500"
        title={`QA verdict: ${qa.verdict || "none recorded"}`}
      >
        <span>QA</span>
        <span className="font-normal">{qa.verdict || "?"}</span>
      </span>
    );
  }
  return (
    <span
      className="inline-flex h-[18px] shrink-0 items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 text-[10px] font-semibold text-amber-500"
      title="QA running"
    >
      <span>QA</span>
      <span>⏳</span>
    </span>
  );
}

function EvalChip({
  scorePct,
  hasJudge,
  qaFailed,
  finished,
}: {
  scorePct: number | null;
  hasJudge: boolean;
  qaFailed: boolean;
  /** The step itself is done — a missing score will never arrive. */
  finished: boolean;
}) {
  if (qaFailed) {
    return (
      <span
        className="inline-flex h-[18px] shrink-0 items-center gap-1 rounded border border-border/60 bg-transparent px-1.5 text-[10px] font-semibold text-muted-foreground/60"
        title="Eval skipped — QA failed"
      >
        <span>Eval</span>
        <span>—</span>
      </span>
    );
  }
  if (!hasJudge) {
    return (
      <span
        className="inline-flex h-[18px] shrink-0 items-center gap-1 rounded border border-border/60 bg-transparent px-1.5 text-[10px] font-semibold text-muted-foreground/60"
        title="No eval defined for this skill yet"
      >
        <span>Eval</span>
        <span>—</span>
      </span>
    );
  }
  if (scorePct === null) {
    // An hourglass on a finished step reads as "still running" forever
    // (FLW Training Guide, Phase 6). Only a step that is actually running
    // or pending gets one.
    if (finished) {
      return (
        <span
          className="inline-flex h-[18px] shrink-0 items-center gap-1 rounded border border-border/60 bg-transparent px-1.5 text-[10px] font-semibold text-muted-foreground"
          title="This step has an eval, but no score was recorded for this run"
        >
          <span>Eval</span>
          <span className="font-normal">no score</span>
        </span>
      );
    }
    return (
      <span
        className="inline-flex h-[18px] shrink-0 items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 text-[10px] font-semibold text-amber-500"
        title="Eval pending"
      >
        <span>Eval</span>
        <span>⏳</span>
      </span>
    );
  }
  const score = Math.round(scorePct);
  const chipClass =
    scorePct >= 80
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-500"
      : scorePct >= 60
        ? "border-amber-500/40 bg-amber-500/10 text-amber-500"
        : "border-rose-500/40 bg-rose-500/10 text-rose-500";
  return (
    <span
      className={cn(
        "inline-flex h-[18px] shrink-0 items-center gap-1 rounded border px-1.5 text-[10px] font-semibold",
        chipClass,
      )}
      title={`Eval score: ${score}/100`}
    >
      <span>Eval</span>
      <span className="tabular-nums">{score}</span>
    </span>
  );
}
