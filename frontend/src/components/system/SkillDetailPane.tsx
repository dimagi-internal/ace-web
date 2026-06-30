import { useEffect, useState } from "react";
import { FileText } from "lucide-react";

import { getSkillDetail } from "../../api/system";
import { Button } from "canopy-ui/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { SkillDetail, SkillSummary } from "./types";
import { ArtifactList } from "./ArtifactList";
import { MarkdownRenderer } from "../MarkdownRenderer";

interface Props {
  skill: SkillSummary;
}

export function SkillDetailPane({ skill }: Props) {
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    setDetail(null);
    setDialogOpen(false);
    getSkillDetail(skill.name)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [skill.name]);

  return (
    <div className="flex flex-col gap-5 p-4">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-foreground">{skill.display_name}</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{skill.description}</p>
      </div>

      {/* View SKILL.md button */}
      {detail?.body_markdown && (
        <>
          <Button
            variant="outline"
            size="sm"
            className="w-full justify-start"
            onClick={() => setDialogOpen(true)}
          >
            <FileText className="mr-2 h-3.5 w-3.5" />
            View full SKILL.md
          </Button>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
              <DialogHeader>
                <DialogTitle>{skill.display_name}</DialogTitle>
                <DialogDescription className="font-mono text-xs">
                  skills/{skill.name}/SKILL.md
                </DialogDescription>
              </DialogHeader>
              <div className="mt-2">
                <MarkdownRenderer content={detail.body_markdown} />
              </div>
            </DialogContent>
          </Dialog>
        </>
      )}

      {/* Metadata grid */}
      <Section title="Metadata">
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          <MetaItem label="Phase" value={skill.phase ?? "utility"} />
          <MetaItem label="Ordinal" value={skill.ordinal ? String(skill.ordinal) : "—"} />
          <MetaItem label="Eval" value={skill.has_judge ? "Yes" : "No"} />
          <MetaItem label="Recurring" value={skill.is_recurring ? "Yes" : "No"} />
          <MetaItem label="Primary output" value={skill.primary_output ?? "—"} />
        </div>
      </Section>

      {/* Artifacts */}
      {(skill.artifacts_produced.length > 0 || skill.artifacts_consumed.length > 0) && (
        <Section title="Artifacts">
          <ArtifactList produced={skill.artifacts_produced} consumed={skill.artifacts_consumed} />
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
