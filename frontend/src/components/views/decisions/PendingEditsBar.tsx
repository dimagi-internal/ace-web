import { GitFork, Undo2 } from "lucide-react";

interface Props {
  count: number;
  onDiscardAll: () => void;
  onForkAndRerun: () => void;
}

/**
 * Sticky action bar at the bottom of the Phases view when the user has
 * buffered one or more decision edits. The "Fork & re-run" button opens
 * the ForkWithEditsDialog; nothing happens to the current run.
 */
export function PendingEditsBar({ count, onDiscardAll, onForkAndRerun }: Props) {
  if (count <= 0) return null;
  const noun = count === 1 ? "pending edit" : "pending edits";
  return (
    <div
      role="region"
      aria-label="Pending decision edits"
      className="sticky bottom-0 z-20 flex items-center gap-3 border-t border-border bg-background/95 px-4 py-3 backdrop-blur"
    >
      <span className="text-sm font-medium text-foreground">
        {count} {noun}
      </span>
      <div className="ml-auto flex gap-2">
        <button
          type="button"
          onClick={onDiscardAll}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs hover:bg-accent"
        >
          <Undo2 className="h-3.5 w-3.5" />
          Discard all
        </button>
        <button
          type="button"
          onClick={onForkAndRerun}
          className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-400 hover:bg-emerald-500/20"
        >
          <GitFork className="h-3.5 w-3.5" />
          Fork & re-run
        </button>
      </div>
    </div>
  );
}
