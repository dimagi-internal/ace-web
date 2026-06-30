import { useEffect, useState } from "react";
import { FileText } from "lucide-react";

import { getAgentDetail } from "../../api/system";
import { Button } from "@canopy/workbench/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { AgentDetail, AgentSummary, PhaseInfo, SkillSummary } from "./types";
import { MarkdownRenderer } from "../MarkdownRenderer";

interface Props {
  agent: AgentSummary;
  skills: SkillSummary[];
  phases: PhaseInfo[];
}

export function AgentDetailPane({ agent, skills, phases }: Props) {
  const [detail, setDetail] = useState<AgentDetail | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    setDetail(null);
    setDialogOpen(false);
    getAgentDetail(agent.name)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [agent.name]);

  // Find the phase this agent owns (from the backend's phase metadata).
  const ownedPhase = phases.find((p) => p.agent === agent.name);
  const ownedSkills = ownedPhase ? skills.filter((s) => s.phase === ownedPhase.name) : [];
  const judgeCount = ownedSkills.filter((s) => s.has_judge).length;
  const recurringCount = ownedSkills.filter((s) => s.is_recurring).length;

  return (
    <div className="flex flex-col gap-5 p-4">
      <div>
        <h2 className="text-lg font-semibold text-foreground">{agent.name}</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{agent.description}</p>
      </div>

      {detail?.body_markdown && (
        <>
          <Button
            variant="outline"
            size="sm"
            className="w-full justify-start"
            onClick={() => setDialogOpen(true)}
          >
            <FileText className="mr-2 h-3.5 w-3.5" />
            View agent definition
          </Button>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
              <DialogHeader>
                <DialogTitle>{agent.name}</DialogTitle>
                <DialogDescription className="font-mono text-xs">
                  agents/{agent.name}.md
                </DialogDescription>
              </DialogHeader>
              <div className="mt-2">
                <MarkdownRenderer content={detail.body_markdown} />
              </div>
            </DialogContent>
          </Dialog>
        </>
      )}

      <Section title="Agent Metadata">
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          <MetaItem label="Phase" value={ownedPhase?.display_name ?? "Lifecycle"} />
          <MetaItem label="Skills" value={String(ownedSkills.length)} />
          <MetaItem label="Evals" value={String(judgeCount)} />
          <MetaItem label="Recurring" value={String(recurringCount)} />
          <MetaItem label="Model" value={agent.model || "—"} />
        </div>
      </Section>
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
