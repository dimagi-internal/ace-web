import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useBeatEditor } from "./BeatEditorContext";
import { sectionLabel } from "./sectionLabels";
import { opCoalesceKey, type PendingChange } from "./types";

interface Props {
  beatId: string;
  kind: string;
  startSec: number;
  endSec: number;
  children: ReactNode;
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

export function BeatCard({ beatId, kind, startSec, endSec, children }: Props) {
  const { state } = useBeatEditor();
  const label = sectionLabel(beatId);
  const dirty = beatIsDirty(beatId, kind, state.buffer);
  const [collapsed, setCollapsed] = useState(false);

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
          onClick={() => setCollapsed((v) => !v)}
          aria-expanded={!collapsed}
          aria-controls={`beat-body-${beatId}`}
          title={collapsed ? "Expand" : "Collapse"}
          className="-ml-1 flex h-6 w-6 flex-shrink-0 items-center justify-center self-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        <h3
          className="cursor-pointer text-base font-semibold"
          onClick={() => setCollapsed((v) => !v)}
        >
          {label.name}
        </h3>
        <span className="font-mono text-xs text-muted-foreground">
          {fmt(startSec)} → {fmt(endSec)} · {(endSec - startSec).toFixed(1)}s
        </span>
        {dirty && (
          <span className="ml-auto rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
            edited
          </span>
        )}
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
