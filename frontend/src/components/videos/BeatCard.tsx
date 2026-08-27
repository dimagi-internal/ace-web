import { type ReactNode } from "react";
import { ChevronDown, ChevronRight, ChevronUp, ChevronDown as ChevronDownIcon, Trash2 } from "lucide-react";
import { useBeatEditor } from "./BeatEditorContext";
import { sectionLabel } from "./sectionLabels";
import { opCoalesceKey, type PendingChange } from "./types";

// Structural controls — present only in the template editor (fullEdit),
// where a template owns its own beat timeline. Reorder is available on every
// beat; remove only on the optional beats (ai_build/problem/impact).
interface StructuralControls {
  removable: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
}

interface Props {
  beatId: string;
  kind: string;
  startSec: number;
  endSec: number;
  children: ReactNode;
  // Controlled collapse state — owned by BeatList so the page can
  // offer expand-all / collapse-all (collapsed beats act as an outline
  // of the video).
  collapsed: boolean;
  onToggleCollapsed: () => void;
  structural?: StructuralControls;
}

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function beatIsDirty(beatId: string, kind: string, buffer: PendingChange[]): boolean {
  return buffer.some((op) => {
    const k = opCoalesceKey(op);
    if (k === `set-narration:${beatId}`) return true;
    if (k === "set-stat:problem" && kind === "body_problem_stat") return true;
    if (k.startsWith("set-stat:impact") && kind === "body_impact_stats") return true;
    if (k.includes("scene-clip") && kind === "body_scene") return true;
    if (k.includes("product-beat") && kind === "body_product_beats") return true;
    return false;
  });
}

export function BeatCard({ beatId, kind, startSec, endSec, children, collapsed, onToggleCollapsed, structural }: Props) {
  const { state } = useBeatEditor();
  const label = sectionLabel(beatId);
  const dirty = beatIsDirty(beatId, kind, state.buffer);

  return (
    <section
      data-beat-id={beatId}
      className="rounded-md border bg-card p-4"
      style={{
        outline: dirty ? "2px solid #FBBF24" : undefined,
        outlineOffset: -2,
      }}
    >
      <header
        className={
          "flex items-baseline gap-3 " +
          (collapsed ? "" : "mb-3")
        }
      >
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-expanded={!collapsed}
          aria-controls={`beat-body-${beatId}`}
          title={collapsed ? "Expand" : "Collapse"}
          className="-ml-1 flex h-6 w-6 flex-shrink-0 items-center justify-center self-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        <h3
          className="cursor-pointer text-base font-semibold"
          onClick={onToggleCollapsed}
        >
          {label.name}
        </h3>
        <span className="font-mono text-xs text-muted-foreground">
          {fmt(startSec)} → {fmt(endSec)} · {(endSec - startSec).toFixed(1)}s
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          {dirty && (
            <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
              edited
            </span>
          )}
          {structural && (
            <div className="flex items-center gap-0.5">
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); structural.onMoveUp(); }}
                disabled={!structural.canMoveUp}
                title="Move beat up"
                aria-label={`Move ${label.name} up`}
                className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30"
              >
                <ChevronUp className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); structural.onMoveDown(); }}
                disabled={!structural.canMoveDown}
                title="Move beat down"
                aria-label={`Move ${label.name} down`}
                className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30"
              >
                <ChevronDownIcon className="h-4 w-4" />
              </button>
              {structural.removable && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); structural.onRemove(); }}
                  title="Remove beat"
                  aria-label={`Remove ${label.name} beat`}
                  className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          )}
        </div>
      </header>
      {!collapsed && (
        <div id={`beat-body-${beatId}`}>
          {label.subtitle && (
            <p className="mb-3 text-sm text-muted-foreground">{label.subtitle}</p>
          )}
          <div className="flex flex-col gap-3">{children}</div>
        </div>
      )}
    </section>
  );
}
