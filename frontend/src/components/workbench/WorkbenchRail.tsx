import type { ReactNode, PointerEvent as ReactPointerEvent } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

export type RailSide = "left" | "right";
export type RailMode = "push" | "overlay";

export interface WorkbenchRailProps {
  children: ReactNode;
  /** Which edge the rail sits on (controls border + chevron direction). */
  side: RailSide;
  /** Short label shown in the expanded rail's header + aria labels. */
  title: string;
  collapsed: boolean;
  onToggle: () => void;
  /** Expanded width in px. Default 400. */
  expandedWidth?: number;
  /** Width of the collapsed icon strip in px. Default 32. */
  collapsedWidth?: number;
  /** "push" (default) reflows the center; "overlay" floats over it. */
  mode?: RailMode;
  /** Enable drag-to-resize (push mode, expanded only). Requires onResize. */
  resizable?: boolean;
  /** Called with the new width (px) while the resize handle is dragged. */
  onResize?: (width: number) => void;
  /** Resize clamp in px. Defaults 220 / 640. */
  minWidth?: number;
  maxWidth?: number;
}

/** Draggable vertical handle on the rail's inner edge. */
function ResizeHandle({
  side,
  width,
  onResize,
  min,
  max,
}: {
  side: RailSide;
  width: number;
  onResize: (w: number) => void;
  min: number;
  max: number;
}) {
  const onPointerDown = (e: ReactPointerEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = width;
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - startX;
      // Left rail grows as you drag right; right rail grows as you drag left.
      const delta = side === "left" ? dx : -dx;
      onResize(Math.max(min, Math.min(max, startW + delta)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.userSelect = "";
    };
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      title="Drag to resize"
      onPointerDown={onPointerDown}
      className={`absolute top-0 bottom-0 z-10 w-1.5 cursor-col-resize hover:bg-primary/30 ${
        side === "left" ? "right-0" : "left-0"
      }`}
    />
  );
}

// Chevron that points "outward" to expand and "inward" to collapse,
// mirrored per side. Right rail: collapse = ChevronRight, expand = ChevronLeft.
function railChevron(side: RailSide, action: "collapse" | "expand") {
  const pointsRight =
    (side === "right" && action === "collapse") ||
    (side === "left" && action === "expand");
  return pointsRight ? ChevronRight : ChevronLeft;
}

export function WorkbenchRail({
  children,
  side,
  title,
  collapsed,
  onToggle,
  expandedWidth = 400,
  collapsedWidth = 32,
  mode = "push",
  resizable = false,
  onResize,
  minWidth = 220,
  maxWidth = 640,
}: WorkbenchRailProps) {
  const borderClass = side === "left" ? "border-r" : "border-l";
  const Collapse = railChevron(side, "collapse");
  const Expand = railChevron(side, "expand");

  // Overlay mode: the rail floats over the center and slides via transform.
  // A single `complementary` region (the floating aside) carries aria-hidden;
  // the collapsed reopen affordance is a plain div so role queries stay
  // unambiguous. Requires a positioned ancestor (WorkbenchLayout adds one).
  if (mode === "overlay") {
    const edge = side === "left" ? "left-0" : "right-0";
    const hiddenTransform = side === "left" ? "translateX(-100%)" : "translateX(100%)";
    return (
      <>
        {collapsed ? (
          <div
            className={`flex shrink-0 flex-col items-center ${borderClass} border-border bg-card`}
            style={{ width: collapsedWidth }}
          >
            <button
              type="button"
              onClick={onToggle}
              className="mt-2 flex h-8 w-8 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground"
              title={`Show ${title} pane`}
              aria-label={`Show ${title} pane`}
            >
              <Expand className="h-4 w-4" />
            </button>
          </div>
        ) : null}
        <aside
          role="complementary"
          aria-hidden={collapsed ? "true" : "false"}
          className={`absolute top-0 ${edge} z-20 flex h-full flex-col ${borderClass} border-border bg-card shadow-lg transition-transform duration-150`}
          style={{
            width: expandedWidth,
            transform: collapsed ? hiddenTransform : "translateX(0)",
          }}
        >
          <div className="flex items-center justify-between border-b border-border px-2 py-1">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
              {title}
            </span>
            <button
              type="button"
              onClick={onToggle}
              className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
              title={`Hide ${title} pane`}
              aria-label={`Hide ${title} pane`}
            >
              <Collapse className="h-4 w-4" />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </aside>
      </>
    );
  }

  // Push mode (default): collapsed → icon strip; expanded → fixed-width pane.
  if (collapsed) {
    return (
      <aside
        className={`flex shrink-0 flex-col items-center ${borderClass} border-border bg-card transition-[width] duration-150`}
        style={{ width: collapsedWidth }}
      >
        <button
          type="button"
          onClick={onToggle}
          className="mt-2 flex h-8 w-8 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground"
          title={`Show ${title} pane`}
          aria-label={`Show ${title} pane`}
          aria-expanded="false"
        >
          <Expand className="h-4 w-4" />
        </button>
      </aside>
    );
  }

  const canResize = resizable && !!onResize;
  return (
    <aside
      className={`relative flex shrink-0 flex-col ${borderClass} border-border bg-card ${
        canResize ? "" : "transition-[width] duration-150"
      }`}
      style={{ width: expandedWidth }}
    >
      <div className="flex items-center justify-between border-b border-border px-2 py-1">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
          {title}
        </span>
        <button
          type="button"
          onClick={onToggle}
          className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
          title={`Hide ${title} pane`}
          aria-label={`Hide ${title} pane`}
          aria-expanded="true"
        >
          <Collapse className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      {canResize ? (
        <ResizeHandle
          side={side}
          width={expandedWidth}
          onResize={onResize!}
          min={minWidth}
          max={maxWidth}
        />
      ) : null}
    </aside>
  );
}
