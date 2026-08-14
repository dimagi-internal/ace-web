import {
  Clock,
  Film,
  Layers,
  LayoutGrid,
  ListTree,
} from "lucide-react";

import { cn } from "@/lib/utils";

export type ViewKind =
  | "hierarchy"
  | "timeline"
  | "workbench"
  | "phase"
  | "story";

export interface ViewTab<K extends string = ViewKind> {
  kind: K;
  label: string;
  /** Falls back to the built-in icon for the known Workbench views. */
  icon?: React.ComponentType<{ className?: string }>;
  /** Small trailing number, e.g. the row count behind a tab. */
  count?: number;
  /** When true, render disabled with the tooltip; click does nothing. */
  disabled?: boolean;
  disabledReason?: string;
}

interface Props<K extends string> {
  current: K;
  tabs: ViewTab<K>[];
  onChange: (k: K) => void;
  /** Container classes. Replaced wholesale so a surface with different
   *  chrome (the public summary's centred column) reuses the tab strip
   *  instead of authoring a second one. */
  className?: string;
}

const ICONS: Record<ViewKind, React.ComponentType<{ className?: string }>> = {
  hierarchy: ListTree,
  timeline: Clock,
  workbench: LayoutGrid,
  phase: Layers,
  story: Film,
};

const DEFAULT_CONTAINER = "border-b border-border bg-background px-6";

/**
 * Tab strip that swaps the page body. Pure presentation — URL state
 * lives in the calling page via useViewMode() / useUrlTab().
 *
 * Pattern modeled on Linear / Notion database-view tabs: small,
 * dense, sits directly under the page header, no shadow.
 *
 * Generic over the tab key so surfaces outside the Workbench (the
 * public run summary) get the same strip without widening `ViewKind`
 * with kinds the Workbench will never render.
 */
export function ViewSwitcher<K extends string>({
  current,
  tabs,
  onChange,
  className,
}: Props<K>) {
  return (
    <div className={cn("flex items-center gap-1", className ?? DEFAULT_CONTAINER)}>
      {tabs.map((t) => {
        const Icon = t.icon ?? ICONS[t.kind as ViewKind];
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
            {Icon && <Icon className="h-3.5 w-3.5" />}
            <span>{t.label}</span>
            {t.count != null && (
              <span className="tabular-nums text-muted-foreground/60">{t.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
