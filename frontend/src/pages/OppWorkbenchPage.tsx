import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getOpp } from "../api/opps";
import type { OppSnapshot, Step } from "../api/types";
import { WorkbenchHeader } from "../components/opps/WorkbenchHeader";
import { EmptyState, ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; snapshot: OppSnapshot };

export default function OppWorkbenchPage() {
  const { slug = "", runId, skill } = useParams();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [selectedSkill, setSelectedSkill] = useState<string | null>(skill ?? null);

  const load = useCallback(() => {
    setState({ kind: "loading" });
    getOpp(slug, runId)
      .then((snapshot) => setState({ kind: "loaded", snapshot }))
      .catch((err) => setState({ kind: "error", message: String(err?.message ?? err) }));
  }, [slug, runId]);

  useEffect(load, [load]);

  useEffect(() => {
    // When the URL gives us a skill param, select it.
    if (skill) setSelectedSkill(skill);
  }, [skill]);

  if (state.kind === "loading") {
    return <LoadingSpinner label={`Loading ${slug}…`} />;
  }
  if (state.kind === "error") {
    return <ErrorState message={state.message} onRetry={load} />;
  }

  const { snapshot } = state;
  const selectedStep: Step | null =
    selectedSkill
      ? snapshot.current_run.steps.find((s) => s.skill_name === selectedSkill) ?? null
      : null;

  return (
    <div className="flex h-full flex-col bg-zinc-950 text-zinc-100">
      <WorkbenchHeader
        opp={snapshot.opp}
        run={snapshot.current_run}
        runs={snapshot.runs}
        onRefresh={load}
      />
      <div className="flex flex-1 overflow-hidden">
        {/* Left pane — implemented in Task 26 */}
        <aside className="w-[180px] border-r border-zinc-800 bg-zinc-950">
          {/* OppSidebar goes here */}
          <div className="p-3 text-xs text-zinc-500">Opps sidebar (Task 26)</div>
        </aside>
        {/* Center pane — implemented in Task 26 */}
        <main className="flex-1 overflow-y-auto">
          {/* SkillList goes here */}
          <div className="p-6 text-zinc-500">
            Skill list for {snapshot.current_run.run_id} (Task 26)
          </div>
        </main>
        {/* Right pane — implemented in Task 27 */}
        <section className="w-[320px] border-l border-zinc-800 bg-zinc-950">
          {selectedStep ? (
            <div className="p-4 text-zinc-500">
              Detail for {selectedStep.skill_name} (Task 27)
            </div>
          ) : (
            <EmptyState title="Select a step" description="Click a row to see its details." />
          )}
        </section>
      </div>
    </div>
  );
}
