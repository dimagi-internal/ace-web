import { useEffect, useMemo, useReducer, useState } from "react";
import { ChevronRight, GitFork, Workflow } from "lucide-react";

import type { OppSnapshot, PhaseInfo, Step } from "@/api/types.ws";
import { ForkOppDialog } from "@/components/opps/ForkOppDialog";
import { Button } from "@/components/ui/button";
import { DecisionsPanel } from "@/components/views/DecisionsPanel";
import { PhaseSkillRow } from "@/components/views/PhaseSkillRow";
import {
  decisionsReducer,
  initialDecisionsEditState,
} from "@/components/views/decisions/decisionsReducer";
import { useAffectedDocs } from "@/components/views/decisions/useAffectedDocs";
import { computeForkPoint } from "@/components/views/decisions/forkPoint";
import { PendingEditsBar } from "@/components/views/decisions/PendingEditsBar";
import { ForkWithEditsDialog } from "@/components/views/decisions/ForkWithEditsDialog";
import { cn } from "@/lib/utils";

interface Props {
  snapshot: OppSnapshot;
  oppSlug: string;
  workspaceSlug: string;
}

/**
 * Vertical phase list on the left; click a phase to expand a detail
 * panel on the right showing the skills in that phase. Click a skill
 * to drill into the same StepDetailPane the Workbench uses.
 *
 * Pure snapshot-driven — no extra API calls. Replaces both the broken
 * React-Flow DAG and the earlier 8-card phase grid.
 */
export function PhaseView({ snapshot, oppSlug, workspaceSlug }: Props) {
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

  // A phase is "running" if any step in it has status "running". Editing
  // decisions is locked while the phase is in progress — otherwise a
  // mid-run write race could clobber freshly-produced decisions.
  const isPhaseRunning = (phaseName: string) => {
    const steps = stepsByPhase.get(phaseName) ?? [];
    return steps.some((s) => s.status === "running");
  };

  // Local-only edit buffer. Nothing persists until the user opens
  // ForkWithEditsDialog and confirms — the current run stays untouched.
  const [editState, dispatchEdit] = useReducer(
    decisionsReducer,
    undefined,
    initialDecisionsEditState,
  );
  const [forkDialogOpen, setForkDialogOpen] = useState(false);

  const allDecisions = useMemo(
    () => snapshot.current_run.decisions ?? [],
    [snapshot.current_run.decisions],
  );
  const affectedDocs = useAffectedDocs({
    decisions: allDecisions,
    edits: editState.buffer,
  });
  const forkPoint = useMemo(
    () =>
      computeForkPoint({
        decisions: allDecisions,
        edits: editState.buffer,
        phases: snapshot.phases,
      }),
    [allDecisions, editState.buffer, snapshot.phases],
  );

  // Warn before a tab close / reload eats pending edits. The browser
  // shows its generic confirmation prompt — the returned string isn't
  // surfaced in modern browsers but `event.returnValue` is the contract.
  useEffect(() => {
    if (editState.buffer.length === 0) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [editState.buffer.length]);

  // Close the fork dialog if the buffer empties out from under it
  // (e.g. user clicked Discard all from a different code path). The
  // dialog's render conditional already hides it, but this clears the
  // open-state flag so reopening behaves correctly.
  useEffect(() => {
    if (editState.buffer.length === 0 && forkDialogOpen) {
      setForkDialogOpen(false);
    }
  }, [editState.buffer.length, forkDialogOpen]);

  // No auto-select on mount: the user has to pick a phase. Earlier
  // versions auto-landed them on the most-urgent phase (qa-failed →
  // open-decision → first-with-steps), but that hijacked the entry
  // experience and made it hard to scan the full list before drilling
  // in. Start everything collapsed.
  const [selectedPhase, setSelectedPhase] = useState<string | null>(null);

  const selectedPhaseInfo = selectedPhase
    ? (phases.find((p) => p.name === selectedPhase) ?? null)
    : null;
  const selectedPhaseSteps = selectedPhase
    ? (stepsByPhase.get(selectedPhase) ?? [])
    : [];

  const selectedPhaseRunning = selectedPhaseInfo
    ? isPhaseRunning(selectedPhaseInfo.name)
    : false;
  // Editing is disabled while the phase is running (mid-run write race)
  // or when we don't have a workspaceSlug to scope the fork POST to —
  // an empty slug would silently 404 against `/api/w//opps/...`.
  const editingDisabled = selectedPhaseRunning || !workspaceSlug;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-[340px] shrink-0 overflow-y-auto border-r border-border bg-background p-4">
          <ul className="flex flex-col gap-2">
            {phases.map((phase) => {
              const phaseDecisions = (
                snapshot.current_run.decisions ?? []
              ).filter((d) => d.phase === phase.name);
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
                sourceRunId={snapshot.current_run.run_id}
                sourceLastActorAt={
                  // The active run's last_actor_at lives in runs[] (RunSummary)
                  // — Run itself only has started_at / completed_at.
                  snapshot.runs.find(
                    (r) => r.run_id === snapshot.current_run.run_id,
                  )?.last_actor_at ?? null
                }
                hidePerPhaseFork={editState.buffer.length > 0}
              />
              <div className="flex-1 overflow-y-auto px-4 pb-6">
                <DecisionsPanel
                  phase={selectedPhaseInfo.name}
                  decisions={allDecisions}
                  editBuffer={editingDisabled ? undefined : editState.buffer}
                  onEdit={
                    editingDisabled
                      ? undefined
                      : (row_id, new_answer) =>
                          dispatchEdit({
                            type: "APPLY_EDIT",
                            row_id,
                            new_answer,
                          })
                  }
                  onRevert={
                    editingDisabled
                      ? undefined
                      : (row_id) =>
                          dispatchEdit({ type: "REVERT_EDIT", row_id })
                  }
                />
                {selectedPhaseRunning && (
                  <div
                    role="status"
                    aria-live="polite"
                    className="mt-2 text-xs text-muted-foreground"
                  >
                    Editing locked while phase is in progress.
                  </div>
                )}
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
      <PendingEditsBar
        count={editState.buffer.length}
        onDiscardAll={() => dispatchEdit({ type: "DISCARD_ALL" })}
        onForkAndRerun={() => setForkDialogOpen(true)}
      />
      {forkDialogOpen &&
        forkPoint &&
        snapshot.current_run.run_id &&
        workspaceSlug && (
          <ForkWithEditsDialog
            open={forkDialogOpen}
            onClose={() => setForkDialogOpen(false)}
            workspaceSlug={workspaceSlug}
            sourceSlug={oppSlug}
            sourceRunId={snapshot.current_run.run_id}
            initialForkAtPhase={forkPoint}
            phases={snapshot.phases}
            edits={editState.buffer}
            affectedDocs={affectedDocs}
          />
        )}
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

function PhaseTile({
  phase,
  steps,
  decisions,
  isSelected,
  onClick,
}: PhaseTileProps) {
  const total = steps.length;
  const complete = steps.filter((s) => s.status === "complete").length;
  const qaFailed = steps.filter((s) => s.status === "qa-failed").length;
  const overriddenDecisions = decisions.filter((d) => d.status === "overridden").length;
  const judged = steps
    .map((s) => s.judge?.score_pct ?? s.judge?.score ?? null)
    .filter((v): v is number => v !== null);
  const meanScore =
    judged.length > 0
      ? judged.reduce((a, b) => a + b, 0) / judged.length
      : null;
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
        {overriddenDecisions > 0 && (
          <span
            className="inline-flex items-center gap-1 rounded-full border border-sky-500/40 bg-sky-500/10 px-1.5 py-0.5 text-[10px] text-sky-400"
            title={`${overriddenDecisions} overridden decision${overriddenDecisions === 1 ? "" : "s"}`}
          >
            {overriddenDecisions} overridden
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
      <div
        className="truncate text-sm font-semibold text-foreground"
        title={phase.display_name}
      >
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
  sourceRunId: string;
  sourceLastActorAt: string | null;
  /** When true, the "Fork from here" button is hidden — there's a
   * sticky "Fork & re-run" bar at the page bottom that picks up the
   * buffered edits and is the right CTA. Two fork buttons on screen
   * at once would be a footgun. */
  hidePerPhaseFork?: boolean;
}

function PhasePanelHeader({
  phase,
  steps,
  oppSlug,
  sourceRunId,
  sourceLastActorAt,
  hidePerPhaseFork,
}: PhasePanelHeaderProps) {
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
    judged.length > 0
      ? judged.reduce((a, b) => a + b, 0) / judged.length
      : null;

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
        {/* Fork CTA: mints a NEW RUN under this opp seeded from the
            current run's upstream phase artifacts. Per-opp state
            (opp.yaml, inputs, calibration) stays shared.
            Hidden when there are pending decision edits — the sticky
            "Fork & re-run" bar at the page bottom is the right CTA
            in that case (it carries the edits into the new run). */}
        {!hidePerPhaseFork && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setForkOpen(true)}
            className="shrink-0 text-xs"
            title={`Fork a new run starting at ${phase.display_name}`}
          >
            <GitFork className="mr-1.5 h-3.5 w-3.5" />
            Fork from here
          </Button>
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground">
        <span>
          <span className="font-medium tabular-nums text-foreground">
            {complete}
          </span>
          <span className="text-muted-foreground">/{total} done</span>
        </span>
        {qaFailed > 0 && (
          <span className="text-rose-500">
            <span className="font-medium tabular-nums">{qaFailed}</span>{" "}
            qa-failed
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
        sourceRunId={sourceRunId}
        forkAtPhase={phase.name}
        forkAtPhaseDisplay={phase.display_name}
        sourceLastActorAt={sourceLastActorAt}
      />
    </header>
  );
}
