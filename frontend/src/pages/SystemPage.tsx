import { useCallback, useEffect, useState } from "react";

import { getSystemOverview } from "../api/system";
import type { SystemSnapshot } from "../components/system/types";
import { SystemHeader } from "../components/system/SystemHeader";
import { EmptyState, ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";
import { PipelineView } from "../components/system/PipelineView";
import { AgentsView } from "../components/system/AgentsView";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; snapshot: SystemSnapshot };

type ViewMode = "pipeline" | "agents";

export default function SystemPage() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [view, setView] = useState<ViewMode>("pipeline");
  const [updateDismissed, setUpdateDismissed] = useState(false);

  const load = useCallback(() => {
    setState({ kind: "loading" });
    getSystemOverview()
      .then((snapshot) => setState({ kind: "loaded", snapshot }))
      .catch((err) => setState({ kind: "error", message: String(err?.message ?? err) }));
  }, []);

  useEffect(load, [load]);

  if (state.kind === "loading") return <LoadingSpinner label="Loading system overview…" />;
  if (state.kind === "error") return <ErrorState message={state.message} onRetry={load} />;

  const { snapshot } = state;

  if (snapshot.warning && snapshot.skills.length === 0) {
    return (
      <EmptyState
        title="ACE plugin not found"
        description={snapshot.warning}
      />
    );
  }

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      <SystemHeader
        snapshot={snapshot}
        view={view}
        onViewChange={setView}
        updateDismissed={updateDismissed}
        onDismissUpdate={() => setUpdateDismissed(true)}
      />
      {view === "pipeline" ? <PipelineView snapshot={snapshot} /> : <AgentsView snapshot={snapshot} />}
    </div>
  );
}
