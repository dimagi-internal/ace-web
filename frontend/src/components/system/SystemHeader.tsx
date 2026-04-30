import { cn } from "@/lib/utils";
import type { SystemSnapshot } from "./types";

type ViewMode = "pipeline" | "agents" | "mcps";

interface Props {
  snapshot: SystemSnapshot;
  view: ViewMode;
  onViewChange: (v: ViewMode) => void;
  updateDismissed: boolean;
  onDismissUpdate: () => void;
}

export function SystemHeader({ snapshot, view, onViewChange, updateDismissed, onDismissUpdate }: Props) {
  const judgeCount = snapshot.skills.filter((s) => s.has_judge).length;
  const recurringCount = snapshot.skills.filter((s) => s.is_recurring).length;
  const mcpToolCount = snapshot.mcps.reduce((acc, s) => acc + s.tools.length, 0);

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
              <strong className="text-foreground">{judgeCount}</strong> judges
            </span>
            <span>
              <strong className="text-foreground">{recurringCount}</strong> recurring
            </span>
            <span>
              <strong className="text-foreground">{mcpToolCount}</strong> MCP tools
            </span>
          </div>
        </div>

        <div className="flex overflow-hidden rounded-md border border-border bg-card text-xs">
          {(
            [
              { mode: "pipeline", label: "Pipeline" },
              { mode: "agents", label: "Agents" },
              { mode: "mcps", label: "MCPs" },
            ] as const
          ).map(({ mode, label }) => (
            <button
              key={mode}
              type="button"
              onClick={() => onViewChange(mode)}
              className={cn(
                "px-3 py-1.5 font-medium",
                view === mode ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
