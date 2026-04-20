import { useState } from "react";
import { Trash2 } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { OppCard, Run } from "../../api/types";
import { Button } from "@/components/ui/button";
import { DeleteOppDialog } from "./DeleteOppDialog";
import { TagEditor } from "./TagEditor";

interface Props {
  opp: OppCard;
  run: Run;
  onRefresh: () => void;
}

export function WorkbenchHeader({ opp, run, onRefresh }: Props) {
  const navigate = useNavigate();
  const [deleteOpen, setDeleteOpen] = useState(false);

  return (
    <>
      <div className="flex items-center gap-4 border-b border-border bg-card px-4 py-2 text-sm">
        <span className="font-semibold text-foreground">{opp.display_name || opp.slug}</span>
        <span className="text-muted-foreground">
          {run.current_phase ? `Phase · ${run.current_phase}` : "—"}
        </span>
        <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
          {run.mode} mode
        </span>
        <TagEditor slug={opp.slug} initialTags={opp.tags ?? []} />
        <span className="ml-auto flex items-center gap-3">
          <button
            type="button"
            onClick={onRefresh}
            className="rounded bg-primary px-3 py-1 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
          >
            ⟳ refresh from Drive
          </button>
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive hover:text-destructive hover:bg-destructive/10"
            onClick={() => setDeleteOpen(true)}
            aria-label="Delete opp"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </span>
      </div>
      <DeleteOppDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        slug={opp.slug}
        displayName={opp.display_name}
        onDeleted={() => navigate("/opps")}
      />
    </>
  );
}
