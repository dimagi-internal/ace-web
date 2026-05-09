import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ChevronRight,
  ExternalLink,
  FileText,
  RotateCcw,
} from "lucide-react";

import type { JudgeCriterionValue, Step } from "@/api/types";
import { cn } from "@/lib/utils";

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

// ─── Drawer sections ─────────────────────────────────────────────────

function SectionHeader({
  source,
  title,
  badge,
  badgeTone,
}: {
  source: string;
  title: string;
  badge?: string;
  badgeTone?: "green" | "red" | "amber" | "muted";
}) {
  const toneClass =
    badgeTone === "green"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
      : badgeTone === "red"
        ? "border-rose-500/40 bg-rose-500/10 text-rose-400"
        : badgeTone === "amber"
          ? "border-amber-500/40 bg-amber-500/10 text-amber-400"
          : "border-border bg-muted/40 text-muted-foreground";
  return (
    <div className="mb-2 flex items-center gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {source}
      </span>
      <span className="text-muted-foreground/50">·</span>
      <span className="text-xs font-semibold text-foreground">{title}</span>
      {badge && (
        <span className={cn("ml-auto rounded border px-1.5 py-0.5 text-[10px] font-semibold", toneClass)}>
          {badge}
        </span>
      )}
    </div>
  );
}

function ProducerSection({ step }: { step: Step }) {
  return (
    <section className="mb-3">
      <SectionHeader
        source={`Producer · ${step.skill_name}`}
        title={step.display_name || step.skill_name}
        badge={step.status === "qa-failed" ? "blocked" : step.status}
        badgeTone={
          step.status === "complete"
            ? "green"
            : step.status === "qa-failed" || step.status === "judge-fail" || step.status === "error"
              ? "red"
              : "muted"
        }
      />
      {step.artifacts.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">No artifacts written yet.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {step.artifacts.map((a) => (
            <li key={a.drive_file_id}>
              <a
                href={a.drive_web_link}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 text-[11px] text-foreground hover:text-primary"
              >
                <FileText className="h-3 w-3 text-muted-foreground" />
                <span className="font-mono">{a.path}</span>
                <ExternalLink className="h-2.5 w-2.5 opacity-60" />
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function QASection({ step }: { step: Step }) {
  const qa = step.qa_result;
  if (!qa) {
    return (
      <section className="mb-3 rounded border border-dashed border-border/50 px-3 py-2">
        <SectionHeader
          source="QA · — none defined"
          title="No QA skill for this producer yet"
          badge="—"
          badgeTone="muted"
        />
        <p className="text-[11px] text-muted-foreground/80">
          When a paired <code className="rounded bg-muted/40 px-1">{step.skill_name}-qa</code>{" "}
          skill ships in the plugin, its structural checks will surface here.
        </p>
      </section>
    );
  }
  const isFail = qa.verdict === "fail";
  const isPass = qa.verdict === "pass";
  const tone: "green" | "red" | "amber" = isPass ? "green" : isFail ? "red" : "amber";
  return (
    <section
      className={cn(
        "mb-3 rounded border px-3 py-2",
        isFail
          ? "border-rose-500/30 bg-rose-500/5"
          : isPass
            ? "border-emerald-500/25 bg-emerald-500/5"
            : "border-amber-500/30 bg-amber-500/5",
      )}
    >
      <SectionHeader
        source={`QA · ${qa.skill}`}
        title={
          isPass
            ? `Passed (${qa.stats.checks_passed}/${qa.stats.checks_run} checks)`
            : isFail
              ? `Failed (${qa.stats.checks_failed} of ${qa.stats.checks_run} checks)`
              : `Incomplete`
        }
        badge={qa.verdict}
        badgeTone={tone}
      />
      {qa.failures.length > 0 && (
        <ul className="mb-2 flex flex-col gap-2">
          {qa.failures.map((f, idx) => (
            <li key={idx} className="rounded border border-rose-500/30 bg-rose-500/5 px-2 py-1.5">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[11px] font-semibold text-foreground">{f.check}</span>
                <span className="text-[9px] uppercase tracking-wider text-rose-400">{f.type}</span>
              </div>
              <div className="mt-1 text-[11px] text-muted-foreground">{f.detail}</div>
              {f.auto_fix_hint && (
                <div className="mt-1.5 rounded border-l-2 border-amber-400/70 bg-amber-400/5 px-2 py-1 text-[11px] text-muted-foreground">
                  <span className="font-semibold text-amber-400">auto_fix_hint:</span>{" "}
                  {f.auto_fix_hint}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {qa.auto_fix && qa.auto_fix.attempted && (
        <div className="inline-flex items-center gap-1.5 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-400">
          <RotateCcw className="h-3 w-3" />
          auto-fix attempted {qa.auto_fix.attempts}× ·{" "}
          {qa.auto_fix.succeeded ? "succeeded" : "still failing"}
        </div>
      )}
      {qa.capture_path && (
        <div className="mt-2 text-[10px] text-muted-foreground/70">
          Capture: <span className="font-mono">{qa.capture_path}</span>
          {qa.ran_at && ` · ran ${qa.ran_at}`}
        </div>
      )}
      {qa.failures.length === 0 && isPass && (
        <p className="text-[11px] text-muted-foreground">All structural checks passed.</p>
      )}
    </section>
  );
}

function EvalSection({ step }: { step: Step }) {
  const judge = step.judge;
  const qaFailed = step.qa_result?.verdict === "fail";
  const evalSkill = `${step.skill_name}-eval`;

  if (qaFailed) {
    return (
      <section className="mb-1 rounded border border-dashed border-border/50 px-3 py-2">
        <SectionHeader
          source={`Eval · ${evalSkill}`}
          title="Skipped — QA gate"
          badge="—"
          badgeTone="muted"
        />
        <p className="text-[11px] text-muted-foreground/80 inline-flex items-center gap-1.5">
          <AlertTriangle className="h-3 w-3 text-rose-400" />
          Eval requires QA pass; will run after QA failures are resolved.
        </p>
      </section>
    );
  }

  if (!judge) {
    if (!step.has_judge) {
      return (
        <section className="mb-1 rounded border border-dashed border-border/50 px-3 py-2">
          <SectionHeader source="Eval · — none defined" title="No eval skill for this producer" badge="—" badgeTone="muted" />
          <p className="text-[11px] text-muted-foreground/80">No eval defined for this producer yet.</p>
        </section>
      );
    }
    return (
      <section className="mb-1 rounded border border-dashed border-border/50 px-3 py-2">
        <SectionHeader source={`Eval · ${evalSkill}`} title="Not yet evaluated" badge="pending" badgeTone="muted" />
      </section>
    );
  }

  const scorePct = judge.score_pct ?? judge.score ?? 0;
  const tone: "green" | "amber" | "red" =
    scorePct >= 80 ? "green" : scorePct >= 60 ? "amber" : "red";
  const entries = Object.entries(judge.criteria || {});

  return (
    <section
      className={cn(
        "mb-1 rounded border px-3 py-2",
        tone === "green"
          ? "border-emerald-500/25 bg-emerald-500/5"
          : tone === "amber"
            ? "border-amber-500/25 bg-amber-500/5"
            : "border-rose-500/25 bg-rose-500/5",
      )}
    >
      <SectionHeader
        source={`Eval · ${evalSkill}`}
        title={`${Math.round(scorePct)}/100`}
        badge={judge.passed === false ? "fail" : judge.passed ? "pass" : "scored"}
        badgeTone={tone}
      />
      {entries.length > 0 && (
        <ul className="mb-2 flex flex-col gap-1">
          {entries.map(([cname, value]) => {
            const { score, note } = readCriterion(value);
            return (
              <li
                key={cname}
                className="grid grid-cols-[140px_36px_1fr] gap-3 py-0.5 text-[11px]"
              >
                <span className="truncate font-semibold text-foreground" title={cname}>
                  {cname}
                </span>
                <span className="text-right font-semibold tabular-nums text-foreground">
                  {score ?? "—"}
                </span>
                {note && <span className="text-muted-foreground">{note}</span>}
              </li>
            );
          })}
        </ul>
      )}
      {judge.rationale && (
        <p className="mt-1 text-[11px] text-muted-foreground">{judge.rationale}</p>
      )}
      {judge.evaluated_at && (
        <div className="mt-1.5 text-[10px] text-muted-foreground/70">
          ran {judge.evaluated_at}
        </div>
      )}
    </section>
  );
}

function readCriterion(value: JudgeCriterionValue): { score: number | null; note: string | null } {
  if (typeof value === "number") return { score: value, note: null };
  if (value && typeof value === "object") {
    const score = typeof value.score === "number" ? value.score : null;
    const note =
      (typeof value.weakness === "string" && value.weakness) ||
      (typeof value.strength === "string" && value.strength) ||
      null;
    return { score, note };
  }
  return { score: null, note: null };
}
