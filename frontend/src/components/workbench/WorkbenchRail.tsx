import type { ReactNode } from "react";
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

  return (
    <aside
      className={`flex shrink-0 flex-col ${borderClass} border-border bg-card transition-[width] duration-150`}
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
    </aside>
  );
}
