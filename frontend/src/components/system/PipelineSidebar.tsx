import { cn } from "@/lib/utils";
import type { PhaseInfo, SkillSummary } from "./types";

// Color palette for phase dots. Assigned by phase ordinal so new phases
// pick up a color automatically without a code change.
const PHASE_COLORS = [
  "bg-blue-500",
  "bg-emerald-500",
  "bg-green-500",
  "bg-cyan-500",
  "bg-amber-500",
  "bg-purple-500",
  "bg-pink-500",
  "bg-indigo-500",
];

export function phaseColor(ordinal: number): string {
  return PHASE_COLORS[(ordinal - 1) % PHASE_COLORS.length];
}

// Filter kind: "all", any phase name, or one of the boolean filters.
export type FilterKind = string;

interface Props {
  skills: SkillSummary[];
  phases: PhaseInfo[];
  filter: FilterKind;
  onFilterChange: (f: FilterKind) => void;
}

export function PipelineSidebar({ skills, phases, filter, onFilterChange }: Props) {
  const judgeCount = skills.filter((s) => s.has_judge).length;
  const recurringCount = skills.filter((s) => s.is_recurring).length;

  return (
    <div className="flex flex-col gap-1 p-2">
      <div className="px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Phases
      </div>
      <SidebarItem
        active={filter === "all"}
        onClick={() => onFilterChange("all")}
        label="All Skills"
        count={skills.length}
      />
      {phases.map((phase) => (
        <SidebarItem
          key={phase.name}
          active={filter === phase.name}
          onClick={() => onFilterChange(phase.name)}
          label={phase.display_name}
          count={skills.filter((s) => s.phase === phase.name).length}
          dotColor={phaseColor(phase.ordinal)}
        />
      ))}

      <div className="mt-3 px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Filters
      </div>
      <SidebarItem
        active={filter === "judge"}
        onClick={() => onFilterChange("judge")}
        label="Has Eval"
        count={judgeCount}
        dotColor="bg-purple-500"
      />
      <SidebarItem
        active={filter === "recurring"}
        onClick={() => onFilterChange("recurring")}
        label="Recurring"
        count={recurringCount}
        dotColor="bg-cyan-500"
      />
    </div>
  );
}

function SidebarItem({
  active,
  onClick,
  label,
  count,
  dotColor,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  dotColor?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs",
        active
          ? "bg-primary/10 text-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      {dotColor && <span className={cn("h-2 w-2 shrink-0 rounded-full", dotColor)} />}
      <span className="flex-1">{label}</span>
      <span className="text-[10px] text-muted-foreground">{count}</span>
    </button>
  );
}
