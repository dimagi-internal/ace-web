import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getOpp, getWorkingSession } from "../api/opps";
import type { OppSnapshot, Run, Step } from "../api/types";
import { ChatPanel } from "../components/opps/ChatPanel";
import { EmptyState, ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";
import { OppSidebar } from "../components/opps/OppSidebar";
import { SkillList } from "../components/opps/SkillList";
import { StepDetailPane } from "../components/opps/StepDetailPane";
import { WorkbenchHeader } from "../components/opps/WorkbenchHeader";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; snapshot: OppSnapshot; priorRun: Run | null };

export default function OppWorkbenchPage() {
  const { slug = "", runId, skill } = useParams();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [selectedSkill, setSelectedSkill] = useState<string | null>(skill ?? null);
  const [workingSessionSlug, setWorkingSessionSlug] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    setWorkingSessionSlug(null);
    getWorkingSession(slug)
      .then((r) => setWorkingSessionSlug(r.working_session_slug))
      .catch(() => setWorkingSessionSlug(null));
  }, [slug]);

  const load = useCallback(() => {
    setState({ kind: "loading" });
    getOpp(slug, runId)
      .then(async (snapshot) => {
        // Fetch the prior run (if any) to compute per-row deltas. The runs
        // list is newest-first; skip the current run, take the next one.
        const currentIdx = snapshot.runs.findIndex(
          (r) => r.run_id === snapshot.current_run.run_id,
        );
        const priorSummary =
          currentIdx >= 0 && currentIdx + 1 < snapshot.runs.length
            ? snapshot.runs[currentIdx + 1]
            : null;
        let priorRun: Run | null = null;
        if (priorSummary) {
          try {
            const priorSnap = await getOpp(slug, priorSummary.run_id);
            priorRun = priorSnap.current_run;
          } catch {
            priorRun = null;
          }
        }
        setState({ kind: "loaded", snapshot, priorRun });
      })
      .catch((err) =>
        setState({ kind: "error", message: String(err?.message ?? err) }),
      );
  }, [slug, runId]);

  useEffect(load, [load]);

  useEffect(() => {
    if (skill) setSelectedSkill(skill);
  }, [skill]);

  if (state.kind === "loading") return <LoadingSpinner label={`Loading ${slug}…`} />;
  if (state.kind === "error") return <ErrorState message={state.message} onRetry={load} />;

  const { snapshot, priorRun } = state;
  const selectedStep: Step | null = selectedSkill
    ? snapshot.current_run.steps.find((s) => s.skill_name === selectedSkill) ?? null
    : null;

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      <WorkbenchHeader
        opp={snapshot.opp}
        run={snapshot.current_run}
        runs={snapshot.runs}
        onRefresh={load}
      />
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-[180px] border-r border-border bg-background">
          <OppSidebar />
        </aside>
        <main className="flex-1 overflow-y-auto">
          <SkillList
            steps={snapshot.current_run.steps}
            priorRunSteps={priorRun?.steps ?? []}
            selectedSkill={selectedSkill}
            onSelect={setSelectedSkill}
          />
        </main>
        <section className="w-[320px] border-l border-border bg-background">
          {selectedStep ? (
            <StepDetailPane
              slug={slug}
              runId={snapshot.current_run.run_id}
              skill={selectedStep.skill_name}
            />
          ) : (
            <EmptyState title="Select a step" description="Click a row to see its details." />
          )}
        </section>
        <section className="w-[400px] shrink-0 border-l border-border bg-background">
          {workingSessionSlug ? (
            <ChatPanel slug={workingSessionSlug} />
          ) : (
            <div className="flex h-full items-center justify-center p-4 text-xs text-muted-foreground">
              Loading chat…
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
