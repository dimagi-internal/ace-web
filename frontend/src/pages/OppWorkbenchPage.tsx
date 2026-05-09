import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { getOpp } from "../api/opps";
import { dropOpp } from "../api/oppCache";
import type { OppSnapshot, Step } from "../api/types";
import { HeatmapView } from "../components/views/HeatmapView";
import { PhaseView } from "../components/views/PhaseView";
import { RunDiffView } from "../components/views/RunDiffView";
import { StoryboardView } from "../components/views/StoryboardView";
import { EmptyState, ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";
import { SkillList } from "../components/opps/SkillList";
import { StepDetailPane } from "../components/opps/StepDetailPane";
import { WorkbenchChatPane } from "../components/opps/WorkbenchChatPane";
import { WorkbenchHeader } from "../components/opps/WorkbenchHeader";
import { ViewSwitcher, type ViewTab } from "../components/views/ViewSwitcher";
import { useOppSocket } from "../hooks/useOppSocket";
import { useViewMode } from "../hooks/useViewMode";

// Per-opp view tabs. "workbench" (the existing 3-pane) is the default.
const VIEW_TABS: ViewTab[] = [
  { kind: "workbench", label: "Workbench" },
  { kind: "phase", label: "Phases" },
  { kind: "heatmap", label: "Heatmap" },
  { kind: "diff", label: "Diff" },
  { kind: "story", label: "Storyboard" },
];

// Cheap human form for the initial loading label, before the API
// returns the real display_name. "leep-paint-collection" → "Leep Paint
// Collection". Ugly enough to be obvious it's a fallback if the slug
// doesn't have words in it.
function humanizeSlug(slug: string): string {
  if (!slug) return "opp";
  return slug
    .split(/[-_]/)
    .map((p) => (p ? p[0].toUpperCase() + p.slice(1) : ""))
    .join(" ");
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; snapshot: OppSnapshot };

export default function OppWorkbenchPage() {
  const { slug = "", runId: pathRunId, skill, workspaceSlug } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  // ?run_id= query param takes precedence; fall back to :runId path segment
  // (kept for backwards-compat with existing /opps/:slug/runs/:runId routes).
  const runId = searchParams.get("run_id") ?? pathRunId;
  const { view, setView } = useViewMode("workbench");
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [selectedSkill, setSelectedSkill] = useState<string | null>(skill ?? null);

  const load = useCallback(
    (opts: { silent?: boolean; force?: boolean } = {}) => {
      if (!opts.silent) {
        setState({ kind: "loading" });
      }
      getOpp(slug, runId ?? undefined, { force: opts.force })
        .then((snapshot) => {
          setState({ kind: "loaded", snapshot });
        })
        .catch((err) => {
          // On silent refresh failure, keep the current state so the UI
          // doesn't flip from "loaded" to "error" on a transient network blip.
          if (!opts.silent) {
            setState({ kind: "error", message: String(err?.message ?? err) });
          }
        });
    },
    [slug, runId],
  );

  useEffect(() => {
    load();
  }, [load]);

  // Subscribe to per-opp WebSocket so the workbench auto-refetches when
  // the chat produces Drive side-effects (see apps/sessions/opp_broadcast).
  // Silent refresh: don't flash the loading spinner on incremental updates.
  // Force-bypass the Drive cache so chat-driven Drive writes show up
  // immediately, not after the TTL window.
  useOppSocket({
    slug,
    runId,
    onOppUpdated: () => {
      dropOpp(slug);
      load({ silent: true });
    },
  });

  useEffect(() => {
    if (skill) setSelectedSkill(skill);
  }, [skill]);

  // Pin the resolved run id into the URL on first load when the user
  // arrived without one (e.g. /opps/<slug> from the list page). The
  // backend already picks the latest run, but the URL stayed bare —
  // making bookmarks / shares ambiguous and the run selector look
  // unselected. `replace: true` so we don't pollute the back stack.
  useEffect(() => {
    if (state.kind !== "loaded") return;
    if (runId) return;
    const resolved =
      state.snapshot.selected_run_id ?? state.snapshot.current_run.run_id;
    if (resolved) {
      setSearchParams({ run_id: resolved }, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.kind]);

  if (state.kind === "loading")
    return <LoadingSpinner label={`Loading ${humanizeSlug(slug)}…`} />;
  if (state.kind === "error") return <ErrorState message={state.message} onRetry={() => load()} />;

  const { snapshot } = state;
  const selectedStep: Step | null = selectedSkill
    ? snapshot.current_run.steps.find((s) => s.skill_name === selectedSkill) ?? null
    : null;

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      <WorkbenchHeader
        opp={snapshot.opp}
        run={snapshot.current_run}
        runs={snapshot.runs ?? []}
        selectedRunId={snapshot.selected_run_id ?? null}
        onRunChange={(id) => setSearchParams({ run_id: id })}
        onRefresh={() => load()}
        workspaceSlug={workspaceSlug}
      />
      <ViewSwitcher current={view} tabs={VIEW_TABS} onChange={setView} />
      {view === "workbench" && (
        <>
          <div className="flex flex-1 overflow-hidden">
            <main className="flex-1 overflow-y-auto">
              <SkillList
                steps={snapshot.current_run.steps}
                priorRunSteps={[]}
                phases={snapshot.phases}
                selectedSkill={selectedSkill}
                onSelect={setSelectedSkill}
              />
            </main>
            <section className="w-[560px] shrink-0 overflow-y-auto border-l border-border bg-background">
              {selectedStep ? (
                <StepDetailPane
                  slug={slug}
                  runId={snapshot.current_run.run_id}
                  skill={selectedStep.skill_name}
                  skillDisplayName={selectedStep.display_name}
                />
              ) : (
                <EmptyState title="Select a step" description="Click a row in the lifecycle to see its details." />
              )}
            </section>
            <aside className="flex w-[400px] shrink-0 flex-col border-l border-border bg-card">
              {selectedStep ? (
                <WorkbenchChatPane
                  slug={slug}
                  runId={snapshot.current_run.run_id}
                  skill={selectedStep.skill_name}
                  skillDisplayName={selectedStep.display_name}
                />
              ) : (
                <div className="flex h-full items-center justify-center px-4 text-center text-xs text-muted-foreground">
                  Select a step in the lifecycle to see its chats
                </div>
              )}
            </aside>
          </div>
        </>
      )}
      {view === "phase" && (
        <div className="min-h-0 flex-1">
          <PhaseView snapshot={snapshot} oppSlug={slug} />
        </div>
      )}
      {view === "heatmap" && workspaceSlug && (
        <div className="min-h-0 flex-1">
          <HeatmapView oppSlug={slug} workspaceSlug={workspaceSlug} />
        </div>
      )}
      {view === "diff" && workspaceSlug && (
        <div className="min-h-0 flex-1">
          <RunDiffView oppSlug={slug} workspaceSlug={workspaceSlug} />
        </div>
      )}
      {view === "story" && workspaceSlug && (
        <div className="min-h-0 flex-1">
          <StoryboardView
            oppSlug={slug}
            workspaceSlug={workspaceSlug}
            runId={snapshot.current_run.run_id}
          />
        </div>
      )}
    </div>
  );
}
