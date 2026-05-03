import { GitBranch, ListTree, Clock } from "lucide-react";

export type ViewKind = "hierarchy" | "flow" | "timeline";

export interface ViewTab {
  kind: ViewKind;
  label: string;
  /** When true, render disabled with the tooltip; click does nothing. */
  disabled?: boolean;
  disabledReason?: string;
}

interface Props {
  current: ViewKind;
  tabs: ViewTab[];
  onChange: (k: ViewKind) => void;
}

const ICONS: Record<ViewKind, React.ComponentType<{ className?: string }>> = {
  hierarchy: ListTree,
  flow: GitBranch,
  timeline: Clock,
};

/**
 * Tab strip that swaps the page body. Pure presentation — URL state
 * lives in the calling page via useViewMode().
 *
 * Pattern modeled on Linear / Notion database-view tabs: small,
 * dense, sits directly under the page header, no shadow.
 */
export function ViewSwitcher({ current, tabs, onChange }: Props) {
  return (
    <div className="flex items-center gap-1 border-b border-border bg-background px-6">
      {tabs.map((t) => {
        const Icon = ICONS[t.kind];
        const active = t.kind === current;
        const cls =
          "flex items-center gap-1.5 px-3 py-2 text-xs transition border-b-2 -mb-px " +
          (active
            ? "text-foreground border-primary font-medium"
            : t.disabled
              ? "text-muted-foreground/50 border-transparent cursor-not-allowed"
              : "text-muted-foreground border-transparent hover:text-foreground");

        return (
          <button
            key={t.kind}
            type="button"
            disabled={t.disabled}
            title={t.disabled ? t.disabledReason : undefined}
            onClick={() => !t.disabled && onChange(t.kind)}
            className={cls}
            aria-pressed={active}
          >
            <Icon className="h-3.5 w-3.5" />
            <span>{t.label}</span>
          </button>
        );
      })}
    </div>
  );
}
