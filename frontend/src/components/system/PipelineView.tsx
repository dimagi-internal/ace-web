import { useState } from "react";

import type { SystemSnapshot, SkillSummary } from "./types";
import { PipelineSidebar, type FilterKind } from "./PipelineSidebar";
import { SkillList } from "./SkillList";
import { SkillDetailPane } from "./SkillDetailPane";
import { EmptyState } from "../opps/LoadingStates";

interface Props {
  snapshot: SystemSnapshot;
}

function applyFilter(skills: SkillSummary[], filter: FilterKind): SkillSummary[] {
  if (filter === "all") return skills;
  if (filter === "judge") return skills.filter((s) => s.has_judge);
  if (filter === "recurring") return skills.filter((s) => s.is_recurring);
  // Phase filter
  return skills.filter((s) => s.phase === filter);
}

export function PipelineView({ snapshot }: Props) {
  const [filter, setFilter] = useState<FilterKind>("all");
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);

  const filtered = applyFilter(snapshot.skills, filter);
  const selected = selectedSkill ? snapshot.skills.find((s) => s.name === selectedSkill) ?? null : null;

  return (
    <div className="flex flex-1 overflow-hidden">
      <aside className="w-[200px] shrink-0 overflow-y-auto border-r border-border">
        <PipelineSidebar skills={snapshot.skills} phases={snapshot.phases} filter={filter} onFilterChange={setFilter} />
      </aside>
      <main className="flex-1 overflow-y-auto">
        <SkillList
          skills={filtered}
          phases={snapshot.phases}
          selectedSkill={selectedSkill}
          onSelectSkill={setSelectedSkill}
        />
      </main>
      <section className="w-[420px] shrink-0 overflow-y-auto border-l border-border">
        {selected ? (
          <SkillDetailPane skill={selected} />
        ) : (
          <div className="flex h-full items-center justify-center">
            <EmptyState title="Select a skill" description="Click a skill to see its details." />
          </div>
        )}
      </section>
    </div>
  );
}
