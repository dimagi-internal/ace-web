import type { ReactNode } from "react";
import { WorkbenchRail, type RailMode } from "./WorkbenchRail";

export interface WorkbenchRailConfig {
  content: ReactNode;
  title: string;
  collapsed: boolean;
  onToggle: () => void;
  expandedWidth?: number;
  collapsedWidth?: number;
  mode?: RailMode;
}

export interface WorkbenchLayoutProps {
  /** Sticky header slot (e.g. WorkbenchHeader with the run picker). */
  header?: ReactNode;
  /** Optional toolbar under the header (e.g. ViewSwitcher tabs). */
  toolbar?: ReactNode;
  /** Left rail — the entity navigator (lifecycle / narrative+runs). */
  left?: WorkbenchRailConfig;
  /** Center detail canvas. Always grows to fill remaining width. */
  center: ReactNode;
  /** Right rail — the inspector / chat. */
  right?: WorkbenchRailConfig;
  className?: string;
}

/**
 * Generic three-pane workbench shell: [left rail | center | right rail].
 * Each rail is independently collapsible (push reflows the center; overlay
 * slides over it). Center always flex-grows. Pure presentational — pass
 * collapse state in via usePaneCollapsed. See README.md for the contract.
 */
export function WorkbenchLayout({
  header,
  toolbar,
  left,
  center,
  right,
  className,
}: WorkbenchLayoutProps) {
  return (
    <div className={`flex h-full w-full flex-col bg-background text-foreground ${className ?? ""}`}>
      {header}
      {toolbar}
      {/* `relative` anchors any overlay-mode rail to this row. */}
      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        {left ? (
          <WorkbenchRail
            side="left"
            title={left.title}
            collapsed={left.collapsed}
            onToggle={left.onToggle}
            expandedWidth={left.expandedWidth}
            collapsedWidth={left.collapsedWidth}
            mode={left.mode}
          >
            {left.content}
          </WorkbenchRail>
        ) : null}
        <main className="min-h-0 flex-1 overflow-y-auto">{center}</main>
        {right ? (
          <WorkbenchRail
            side="right"
            title={right.title}
            collapsed={right.collapsed}
            onToggle={right.onToggle}
            expandedWidth={right.expandedWidth}
            collapsedWidth={right.collapsedWidth}
            mode={right.mode}
          >
            {right.content}
          </WorkbenchRail>
        ) : null}
      </div>
    </div>
  );
}
