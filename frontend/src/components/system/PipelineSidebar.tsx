import { cn } from "@/lib/utils";
import type { SkillSummary } from "./types";

const PHASE_COLORS: Record<string, string> = {
  "app-building": "bg-blue-500",
  "connect-setup": "bg-green-500",
  "llo-management": "bg-amber-500",
  "closeout": "bg-purple-500",
};

const PHASE_LABELS: Record<string, string> = {
  "app-building": "App Building",
  "connect-setup": "Connect Setup",
  "llo-management": "LLO Management",
  "closeout": "Closeout",
};

type FilterKind = "all" | "app-building" | "connect-setup" | "llo-management" | "closeout" | "judge" | "gate" | "recurring";

interface Props {
  skills: SkillSummary[];
  phases: string[];
  filter: FilterKind;
  onFilterChange: (f: FilterKind) => void;
}

export type { FilterKind };

export function PipelineSidebar({ skills, phases, filter, onFilterChange }: Props) {
  const judgeCount = skills.filter((s) => s.has_judge).length;
  const gateCount = skills.filter((s) => s.is_gate).length;
  const recurringCount = skills.filter((s) => s.is_recurring).length;

  return (
    <div className="flex flex-col gap-1 p-2">
      <div className="px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Phases
      </div>
      <SidebarItem active={filter === "all"} onClick={() => onFilterChange("all")} label="All Skills" count={skills.length} />
      {phases.map((phase) => (
        <SidebarItem
          key={phase}
          active={filter === phase}
          onClick={() => onFilterChange(phase as FilterKind)}
          label={PHASE_LABELS[phase] ?? phase}
          count={skills.filter((s) => s.phase === phase).length}
          dotColor={PHASE_COLORS[phase]}
        />
      ))}

      <div className="mt-3 px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Filters
      </div>
      <SidebarItem active={filter === "judge"} onClick={() => onFilterChange("judge")} label="Has Judge" count={judgeCount} dotColor="bg-purple-500" />
      <SidebarItem active={filter === "gate"} onClick={() => onFilterChange("gate")} label="Has Gate" count={gateCount} dotColor="bg-amber-500" />
      <SidebarItem active={filter === "recurring"} onClick={() => onFilterChange("recurring")} label="Recurring" count={recurringCount} dotColor="bg-cyan-500" />
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
