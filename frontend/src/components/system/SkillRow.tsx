import { cn } from "@/lib/utils";
import type { SkillSummary } from "./types";

interface Props {
  skill: SkillSummary;
  isSelected: boolean;
  onClick: () => void;
}

export function SkillRow({ skill, isSelected, onClick }: Props) {
  const producedCount = skill.artifacts_produced.length;
  const extraCount = Math.max(0, producedCount - 1);

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-3 border-b border-border px-4 py-2.5 text-left text-xs transition-colors",
        isSelected ? "bg-primary/10 border-l-2 border-l-primary" : "hover:bg-accent",
      )}
    >
      <span
        className={cn(
          "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold",
          isSelected ? "border-primary text-primary" : "border-border text-muted-foreground",
        )}
      >
        {skill.ordinal ?? "—"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="font-medium text-foreground">{skill.display_name}</div>
        {skill.primary_output && (
          <div className="flex items-center gap-1.5 truncate">
            <span className="font-mono text-[10px] text-muted-foreground truncate">
              {skill.primary_output}
            </span>
            {extraCount > 0 && (
              <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground">
                +{extraCount} more
              </span>
            )}
          </div>
        )}
      </div>
      <div className="flex shrink-0 gap-1">
        {skill.has_judge && <Badge label="Judge" className="bg-purple-500/15 text-purple-400" />}
        {skill.is_recurring && <Badge label="Recurring" className="bg-cyan-500/15 text-cyan-400" />}
      </div>
    </button>
  );
}

function Badge({ label, className }: { label: string; className: string }) {
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase", className)}>
      {label}
    </span>
  );
}
