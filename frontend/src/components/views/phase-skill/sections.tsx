// Drawer sections for the Phase view's collapsible PhaseSkillRow.
//
// Producer / QA / Eval sections were originally inlined inside
// PhaseSkillRow.tsx. Moved here so PhaseSkillRow.tsx is a tighter
// row-render-and-collapse-toggle component and so the section bodies
// (which carry all the conditional verdict / rationale / criterion
// logic) can be edited or unit-tested without scrolling past the
// chip helpers.
import { AlertTriangle, ExternalLink, RotateCcw } from "lucide-react";

import type { Decision, JudgeCriterionValue, Step } from "@/api/types.ws";
import { Glossed } from "@/components/glossary/Glossed";
import { useViewer } from "@/components/viewers/ViewerContext";
import { cn } from "@/lib/utils";

/** Statuses after which nothing more will be written for the step — a
 *  missing verdict is missing, not pending. */
const FINISHED_STATUSES = new Set(["complete", "qa-failed", "judge-fail", "error", "skipped"]);

export function isFinished(status: string): boolean {
  return FINISHED_STATUSES.has(status);
}

export function ProducerSection({ step }: { step: Step }) {
  const viewer = useViewer();
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
            <li key={a.drive_file_id} className="flex items-center gap-1.5">
              {viewer ? (
                // Opens in the page; the icon beside it still goes to Drive.
                <button
                  type="button"
                  onClick={() =>
                    viewer.open({
                      type: "file",
                      fileId: a.drive_file_id,
                      name: a.name || a.path,
                      driveLink: a.drive_web_link,
                      skill: step.skill_name,
                    })
                  }
                  className="font-mono text-[11px] text-foreground hover:text-primary hover:underline"
                  title="Open here"
                >
                  {a.path}
                </button>
              ) : (
                <span className="font-mono text-[11px] text-foreground">{a.path}</span>
              )}
              <a
                href={a.drive_web_link}
                target="_blank"
                rel="noreferrer"
                className="text-muted-foreground hover:text-primary"
                title="Open in Drive"
                aria-label={`Open ${a.path} in Drive`}
              >
                <ExternalLink className="h-2.5 w-2.5 opacity-70" />
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function QASection({ step }: { step: Step }) {
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

export function EvalSection({
  step,
  finished = isFinished(step.status),
}: {
  step: Step;
  /** Nothing more will be written for this step (see PhaseSkillRow). */
  finished?: boolean;
}) {
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
    if (finished) {
      return (
        <section className="mb-1 rounded border border-dashed border-border/50 px-3 py-2">
          <SectionHeader source={`Eval · ${evalSkill}`} title="No score recorded" badge="—" badgeTone="muted" />
          <p className="text-[11px] text-muted-foreground/80">
            This step has an eval, but no score was recorded for this run.
          </p>
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

/**
 * What this skill decided — each question, the answer the run went with, and
 * whether a person overrode the AI's default. The decisions ARE much of the
 * story of a run, and in a replay they land here as the step finishes.
 */
export function DecisionsSection({ decisions }: { decisions: readonly Decision[] }) {
  return (
    <section className="mb-3 rounded border border-sky-500/25 bg-sky-500/5 px-3 py-2">
      <SectionHeader
        source="Decisions"
        title={`${decisions.length} made`}
        badge={
          decisions.some((d) => d.status === "overridden")
            ? `${decisions.filter((d) => d.status === "overridden").length} overridden`
            : undefined
        }
        badgeTone="muted"
      />
      <ul className="flex flex-col gap-1.5">
        {decisions.map((d) => {
          const overridden = d.status === "overridden";
          return (
            <li key={d.id} className="text-[11px]">
              <div className="text-muted-foreground">
                <Glossed text={d.question} />
              </div>
              <div className="flex flex-wrap items-baseline gap-1.5">
                <span className="font-medium text-foreground">
                  <Glossed text={overridden ? d.override : d.ai_default} />
                </span>
                {overridden ? (
                  <span className="rounded bg-sky-500/15 px-1 text-[10px] text-sky-500">
                    overridden · AI said “{d.ai_default}”
                  </span>
                ) : (
                  <span className="rounded bg-muted px-1 text-[10px] text-muted-foreground">
                    AI default
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// ─── Internals ────────────────────────────────────────────────────────

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
