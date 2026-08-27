import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, ChevronRight, Film } from "lucide-react";
import { sectionLabel } from "./sectionLabels";

interface Props {
  workspaceSlug: string;
  programSlug: string;
  programName: string;
  runs: { run_id: string; has_output: boolean }[];
  currentRunId: string | null;
  // Beats of the CURRENT run (the only spec loaded). Other runs expand on
  // navigation.
  beats: { id: string; kind: string; seconds: number }[];
}

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function scrollToBeat(id: string) {
  document.getElementById(`beat-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

/**
 * Left-rail navigator for the video workbench: the program slug at top,
 * its runs underneath, and (for the loaded run) its beats as sub-items.
 * Clicking a run navigates to it; clicking a beat scrolls the center
 * editor to that beat. The bulky beat editor stays in the center pane.
 */
export function VideoNavRail({
  workspaceSlug,
  programSlug,
  programName,
  runs,
  currentRunId,
  beats,
}: Props) {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(currentRunId ? [currentRunId] : []),
  );

  const toggle = (runId: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });

  // Newest run first.
  const ordered = [...runs].reverse();

  return (
    <div className="flex flex-col text-sm">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <Film className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="truncate font-medium" title={programName}>
          {programName}
        </span>
      </div>

      <div className="flex flex-col py-1">
        {ordered.length === 0 ? (
          <div className="px-3 py-2 text-xs text-muted-foreground">No runs yet.</div>
        ) : null}

        {ordered.map((r) => {
          const isCurrent = r.run_id === currentRunId;
          const isOpen = expanded.has(r.run_id);
          return (
            <div key={r.run_id}>
              <div
                className={`group flex items-center gap-1 px-2 py-1.5 ${
                  isCurrent ? "bg-muted" : "hover:bg-muted/60"
                }`}
              >
                <button
                  type="button"
                  onClick={() => toggle(r.run_id)}
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-foreground"
                  aria-label={isOpen ? `Collapse ${r.run_id}` : `Expand ${r.run_id}`}
                  aria-expanded={isOpen}
                >
                  {isOpen ? (
                    <ChevronDown className="h-3.5 w-3.5" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() =>
                    navigate(`/w/${workspaceSlug}/videos/${programSlug}/runs/${r.run_id}`)
                  }
                  className={`flex flex-1 items-center gap-2 truncate text-left ${
                    isCurrent ? "font-medium text-foreground" : "text-muted-foreground hover:text-foreground"
                  }`}
                  title={r.run_id}
                >
                  <span className="truncate font-mono text-xs">{r.run_id}</span>
                  {!r.has_output ? (
                    <span className="shrink-0 text-[10px] text-amber-600 dark:text-amber-500">
                      no render
                    </span>
                  ) : null}
                </button>
              </div>

              {isOpen && isCurrent && beats.length > 0 ? (
                <div className="flex flex-col">
                  {beats.map((b, i) => {
                    const start = beats.slice(0, i).reduce((s, x) => s + x.seconds, 0);
                    return (
                      <button
                        key={b.id}
                        type="button"
                        onClick={() => scrollToBeat(b.id)}
                        className="flex items-center justify-between gap-2 py-1 pl-9 pr-3 text-left text-xs text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                        title={sectionLabel(b.id).name}
                      >
                        <span className="truncate">{sectionLabel(b.id).name}</span>
                        <span className="shrink-0 tabular-nums text-[10px] text-muted-foreground/70">
                          {fmt(start)}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : isOpen && !isCurrent ? (
                <button
                  type="button"
                  onClick={() =>
                    navigate(`/w/${workspaceSlug}/videos/${programSlug}/runs/${r.run_id}`)
                  }
                  className="py-1 pl-9 pr-3 text-left text-[11px] text-muted-foreground/70 hover:text-foreground"
                >
                  Open this run to see its beats
                </button>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
