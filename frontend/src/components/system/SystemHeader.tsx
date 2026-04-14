import { cn } from "@/lib/utils";
import type { SystemSnapshot } from "./types";

type ViewMode = "pipeline" | "agents";

interface Props {
  snapshot: SystemSnapshot;
  view: ViewMode;
  onViewChange: (v: ViewMode) => void;
  updateDismissed: boolean;
  onDismissUpdate: () => void;
}

export function SystemHeader({ snapshot, view, onViewChange, updateDismissed, onDismissUpdate }: Props) {
  const judgeCount = snapshot.skills.filter((s) => s.has_judge).length;
  const gateCount = snapshot.skills.filter((s) => s.is_gate).length;

  return (
    <div className="flex flex-col border-b border-border">
      {/* Update banner */}
      {snapshot.update_available && !updateDismissed && (
        <div className="flex items-center justify-between bg-status-info/10 px-4 py-2 text-xs text-status-info">
          <span>
            ACE plugin <strong>v{snapshot.remote_version}</strong> is available (you have{" "}
            <strong>v{snapshot.plugin_version}</strong>). Run{" "}
            <code className="rounded bg-card px-1.5 py-0.5 font-mono">/ace:update</code> in Claude Code to
            upgrade.
          </span>
          <button type="button" onClick={onDismissUpdate} className="ml-4 text-muted-foreground hover:text-foreground">
            Dismiss
          </button>
        </div>
      )}

      {/* Subheader */}
      <div className="flex items-center justify-between px-4 py-2">
        <div className="flex items-center gap-4">
          <h1 className="text-base font-semibold text-foreground">System Blueprint</h1>
          <div className="flex gap-3 text-xs text-muted-foreground">
            <span>
              <strong className="text-foreground">{snapshot.skills.length}</strong> skills
            </span>
            <span>
              <strong className="text-foreground">{snapshot.agents.length}</strong> agents
            </span>
            <span>
              <strong className="text-foreground">{snapshot.phases.length}</strong> phases
            </span>
            <span>
              <strong className="text-foreground">{gateCount}</strong> gates
            </span>
            <span>
              <strong className="text-foreground">{judgeCount}</strong> judges
            </span>
          </div>
        </div>

        <div className="flex overflow-hidden rounded-md border border-border bg-card text-xs">
          {(["pipeline", "agents"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => onViewChange(mode)}
              className={cn(
                "px-3 py-1.5 font-medium capitalize",
                view === mode ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
