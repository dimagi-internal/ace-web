import { useEffect, useState } from "react";
import { getAgentDetail } from "../../api/system";
import type { AgentDetail, AgentSummary, SkillSummary } from "./types";
import { MarkdownRenderer } from "../MarkdownRenderer";

const AGENT_PHASES: Record<string, string> = {
  "app-builder": "app-building",
  "connect-setup": "connect-setup",
  "llo-manager": "llo-management",
  "closeout": "closeout",
};

interface Props {
  agent: AgentSummary;
  skills: SkillSummary[];
}

export function AgentDetailPane({ agent, skills }: Props) {
  const [detail, setDetail] = useState<AgentDetail | null>(null);

  useEffect(() => {
    setDetail(null);
    getAgentDetail(agent.name)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [agent.name]);

  const phase = AGENT_PHASES[agent.name];
  const ownedSkills = phase ? skills.filter((s) => s.phase === phase) : [];
  const judgeCount = ownedSkills.filter((s) => s.has_judge).length;
  const gateCount = ownedSkills.filter((s) => s.is_gate).length;

  return (
    <div className="flex flex-col gap-5 overflow-y-auto p-4">
      <div>
        <h2 className="text-lg font-semibold text-foreground">{agent.name}</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{agent.description}</p>
      </div>

      <Section title="Agent Metadata">
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          <MetaItem label="Phase" value={phase ?? "Lifecycle"} />
          <MetaItem label="Skills" value={String(ownedSkills.length)} />
          <MetaItem label="Gates" value={String(gateCount)} />
          <MetaItem label="Judges" value={String(judgeCount)} />
          <MetaItem label="Model" value={agent.model || "—"} />
        </div>
      </Section>

      {detail?.body_markdown && (
        <Section title="Agent Definition">
          <MarkdownRenderer content={detail.body_markdown} />
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 border-b border-border pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h3>
      {children}
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className="font-medium text-foreground">{value}</div>
    </div>
  );
}
