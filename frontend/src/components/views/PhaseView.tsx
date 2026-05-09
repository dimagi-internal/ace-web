import { useEffect, useMemo, useState } from "react";
import { ChevronRight, GitFork, Workflow } from "lucide-react";

import type { OppSnapshot, PhaseInfo, Step } from "@/api/types";
import { ForkOppDialog } from "@/components/opps/ForkOppDialog";
import { Button } from "@/components/ui/button";
import { DecisionsPanel } from "@/components/views/DecisionsPanel";
import { PhaseSkillRow } from "@/components/views/PhaseSkillRow";
import { cn } from "@/lib/utils";

interface Props {
  snapshot: OppSnapshot;
  oppSlug: string;
}

/**
 * Vertical phase list on the left; click a phase to expand a detail
 * panel on the right showing the skills in that phase. Click a skill
 * to drill into the same StepDetailPane the Workbench uses.
 *
 * Pure snapshot-driven — no extra API calls. Replaces both the broken
 * React-Flow DAG and the earlier 8-card phase grid.
 */
export function PhaseView({ snapshot, oppSlug }: Props) {
  const phases = useMemo(
    () => [...snapshot.phases].sort((a, b) => a.ordinal - b.ordinal),
    [snapshot.phases],
  );

  const stepsByPhase = useMemo(() => {
    const m = new Map<string, Step[]>();
    for (const s of snapshot.current_run.steps) {
      const arr = m.get(s.phase);
      if (arr) arr.push(s);
      else m.set(s.phase, [s]);
    }
    for (const arr of m.values()) arr.sort((a, b) => a.ordinal - b.ordinal);
    return m;
  }, [snapshot.current_run.steps]);

  const [selectedPhase, setSelectedPhase] = useState<string | null>(null);

  // Auto-select on first load. Priority: phase with a qa-failed step
  // (most urgent system signal) → phase with an open decision (most
  // actionable for a reviewer) → first phase with steps.
  useEffect(() => {
    if (selectedPhase) return;
    const decisions = snapshot.current_run.decisions ?? [];
    const qaFailedPhase = phases.find((p) =>
      (stepsByPhase.get(p.name) ?? []).some((s) => s.status === "qa-failed"),
    );
    if (qaFailedPhase) {
      setSelectedPhase(qaFailedPhase.name);
      return;
    }
    const openDecisionPhase = phases.find((p) =>
      decisions.some((d) => d.phase === p.name && d.status === "open"),
    );
    if (openDecisionPhase) {
      setSelectedPhase(openDecisionPhase.name);
      return;
    }
    const firstWithSteps = phases.find(
      (p) => (stepsByPhase.get(p.name) ?? []).length > 0,
    );
    if (firstWithSteps) setSelectedPhase(firstWithSteps.name);
  }, [phases, stepsByPhase, selectedPhase, snapshot.current_run.decisions]);

  const selectedPhaseInfo = selectedPhase
    ? phases.find((p) => p.name === selectedPhase) ?? null
    : null;
  const selectedPhaseSteps = selectedPhase
    ? stepsByPhase.get(selectedPhase) ?? []
    : [];

  return (
    <div className="flex h-full overflow-hidden">
      <aside className="w-[340px] shrink-0 overflow-y-auto border-r border-border bg-background p-4">
        <ul className="flex flex-col gap-2">
          {phases.map((phase) => {
            const phaseDecisions = (snapshot.current_run.decisions ?? []).filter(
              (d) => d.phase === phase.name,
            );
            return (
              <li key={phase.name}>
                <PhaseTile
                  phase={phase}
                  steps={stepsByPhase.get(phase.name) ?? []}
                  decisions={phaseDecisions}
                  isSelected={selectedPhase === phase.name}
                  onClick={() => setSelectedPhase(phase.name)}
                />
              </li>
            );
          })}
        </ul>
      </aside>

      <section className="relative flex-1 overflow-hidden">
        {selectedPhaseInfo ? (
            <div
              key={selectedPhaseInfo.name}
              className="flex h-full animate-in fade-in slide-in-from-right-2 flex-col duration-200"
            >
              <PhasePanelHeader
                phase={selectedPhaseInfo}
                steps={selectedPhaseSteps}
                oppSlug={oppSlug}
              />
              <div className="flex-1 overflow-y-auto px-4 pb-6">
                <DecisionsPanel
                  phase={selectedPhaseInfo.name}
                  decisions={snapshot.current_run.decisions ?? []}
                />
                {selectedPhaseSteps.length === 0 ? (
                  <div className="flex h-full items-center justify-center text-center text-sm text-muted-foreground">
                    No steps recorded for this phase yet.
                  </div>
                ) : (
                  <section className="mt-4">
                    <header className="mb-2 flex items-center gap-2.5">
                      <span className="inline-flex items-center gap-1.5 rounded-md border border-primary/40 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-primary">
                        <Workflow className="h-3 w-3" />
                        Skills
                      </span>
                      <span className="text-xs font-medium text-foreground">
                        {selectedPhaseSteps.length}
                      </span>
                    </header>
                    <ul className="flex flex-col gap-1.5">
                      {selectedPhaseSteps.map((step) => (
                        <li key={step.skill_name}>
                          <PhaseSkillRow
                            step={step}
                            oppSlug={oppSlug}
                            runId={snapshot.current_run.run_id}
                          />
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </div>
            </div>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Select a phase to see its skills.
          </div>
        )}
      </section>
    </div>
  );
}

interface PhaseTileProps {
  phase: PhaseInfo;
  steps: Step[];
  decisions: { status: string }[];
  isSelected: boolean;
  onClick: () => void;
}

function PhaseTile({ phase, steps, decisions, isSelected, onClick }: PhaseTileProps) {
  const total = steps.length;
  const complete = steps.filter((s) => s.status === "complete").length;
  const qaFailed = steps.filter((s) => s.status === "qa-failed").length;
  const openDecisions = decisions.filter((d) => d.status === "open").length;
  const judged = steps
    .map((s) => s.judge?.score_pct ?? s.judge?.score ?? null)
    .filter((v): v is number => v !== null);
  const meanScore =
    judged.length > 0 ? judged.reduce((a, b) => a + b, 0) / judged.length : null;
  const completionPct = total === 0 ? 0 : (complete / total) * 100;

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={isSelected}
      className={cn(
        "group flex w-full flex-col gap-2 rounded-lg border p-3 text-left transition-all",
        isSelected
          ? "border-primary bg-primary/5 shadow-sm"
          : "border-border bg-card hover:border-border/80 hover:bg-accent/40",
      )}
    >
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Phase {phase.ordinal}
        </span>
        <span className="ml-auto" />
        {openDecisions > 0 && (
          <span
            className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-500"
            title={`${openDecisions} open decision${openDecisions === 1 ? "" : "s"}`}
          >
            ? {openDecisions}
          </span>
        )}
        {qaFailed > 0 && (
          <span
            className="inline-flex items-center gap-1 rounded-full border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5 text-[10px] text-rose-500"
            title={`${qaFailed} step${qaFailed === 1 ? "" : "s"} blocked by QA failures`}
          >
            ✗ {qaFailed}
          </span>
        )}
        <ChevronRight
          className={cn(
            "h-4 w-4 shrink-0 transition-transform",
            isSelected
              ? "rotate-90 text-foreground"
              : "text-muted-foreground/60 group-hover:text-foreground",
          )}
        />
      </div>
      <div className="truncate text-sm font-semibold text-foreground" title={phase.display_name}>
        {phase.display_name}
      </div>
      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span className="tabular-nums">
          {complete}/{total} done
        </span>
        <span className="tabular-nums">
          {meanScore !== null ? `${Math.round(meanScore)}/100` : "—"}
        </span>
      </div>
      <div className="h-1 w-full overflow-hidden rounded bg-muted">
        <span
          className={cn(
            "block h-full transition-all",
            completionPct === 0 ? "" : "bg-primary",
          )}
          style={{ width: `${completionPct}%` }}
        />
      </div>
    </button>
  );
}

interface PhasePanelHeaderProps {
  phase: PhaseInfo;
  steps: Step[];
  oppSlug: string;
}

function PhasePanelHeader({ phase, steps, oppSlug }: PhasePanelHeaderProps) {
  const [forkOpen, setForkOpen] = useState(false);
  const total = steps.length;
  const complete = steps.filter((s) => s.status === "complete").length;
  const qaFailed = steps.filter((s) => s.status === "qa-failed").length;
  const failed = steps.filter(
    (s) => s.status === "judge-fail" || s.status === "error",
  ).length;
  const judged = steps
    .map((s) => s.judge?.score_pct ?? s.judge?.score ?? null)
    .filter((v): v is number => v !== null);
  const meanScore =
    judged.length > 0 ? judged.reduce((a, b) => a + b, 0) / judged.length : null;

  return (
    <header className="shrink-0 border-b border-border bg-card/30 px-6 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Phase {phase.ordinal} · {phase.agent}
          </div>
          <h2 className="mt-1 text-xl font-semibold text-foreground">
            {phase.display_name}
          </h2>
        </div>
        {/* Fork CTA: lets a viewer branch the run from this phase boundary
            so they can re-run the rest of the lifecycle as a separate
            opp without losing the source. The Drive copy is recursive
            and can take 30-60s — see ForkOppDialog for the wait state. */}
        <Button
          variant="outline"
          size="sm"
          onClick={() => setForkOpen(true)}
          className="shrink-0 text-xs"
          title={`Fork this opp into a new one starting at ${phase.display_name}`}
        >
          <GitFork className="mr-1.5 h-3.5 w-3.5" />
          Fork from here
        </Button>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground">
        <span>
          <span className="font-medium tabular-nums text-foreground">{complete}</span>
          <span className="text-muted-foreground">/{total} done</span>
        </span>
        {qaFailed > 0 && (
          <span className="text-rose-500">
            <span className="font-medium tabular-nums">{qaFailed}</span> qa-failed
          </span>
        )}
        {failed > 0 && (
          <span className="text-rose-500">
            <span className="font-medium tabular-nums">{failed}</span> failed
          </span>
        )}
        {meanScore !== null && (
          <span>
            mean{" "}
            <span className="font-medium tabular-nums text-foreground">
              {Math.round(meanScore)}/100
            </span>
          </span>
        )}
      </div>
      <ForkOppDialog
        open={forkOpen}
        onOpenChange={setForkOpen}
        sourceSlug={oppSlug}
        forkAtPhase={phase.name}
        forkAtPhaseDisplay={phase.display_name}
      />
    </header>
  );
}
