import { useEffect, useState } from "react";
import { FileText, MessageSquare, X } from "lucide-react";

import type { Step } from "@/api/types.ws";
import { StepChatPane } from "@/components/opps/StepChatPane";
import { StepDetailPane } from "@/components/opps/StepDetailPane";
import { cn } from "@/lib/utils";

type Tab = "detail" | "chat";

/**
 * One step, opened from the Phases screen: its artifacts (previewed in
 * place), eval, and the chats about it. Addressable — the page drives it from
 * `/runs/<run>/steps/<skill>`, so a step link someone shares opens here.
 *
 * Lives in the right-hand column, in place of the run's flow rail, so the
 * phase list and the phase's skills stay on screen beside it. Esc closes.
 */
export function StepDrawer({
  workspaceSlug,
  oppSlug,
  runId,
  step,
  onClose,
}: {
  workspaceSlug: string;
  oppSlug: string;
  runId: string;
  step: Step;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("detail");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      // Leave Esc to a dialog (artifact editor, viewer) that owns it.
      if (document.querySelector("[role='dialog']")) return;
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const tabCls = (active: boolean) =>
    cn(
      "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs transition",
      active
        ? "border-primary font-medium text-foreground"
        : "border-transparent text-muted-foreground hover:text-foreground",
    );

  return (
    <aside
      aria-label={`Step: ${step.display_name || step.skill_name}`}
      className="flex w-[min(46vw,720px)] min-w-[420px] shrink-0 flex-col border-l border-border bg-background animate-in fade-in slide-in-from-right-2 duration-150"
    >
      <div className="flex items-center border-b border-border pl-1 pr-2">
        <button type="button" className={tabCls(tab === "detail")} aria-pressed={tab === "detail"} onClick={() => setTab("detail")}>
          <FileText className="h-3.5 w-3.5" />
          Detail
        </button>
        <button type="button" className={tabCls(tab === "chat")} aria-pressed={tab === "chat"} onClick={() => setTab("chat")}>
          <MessageSquare className="h-3.5 w-3.5" />
          Chat
        </button>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close step"
          title="Close (Esc)"
          className="ml-auto rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1">
        {tab === "detail" ? (
          <StepDetailPane
            workspaceSlug={workspaceSlug}
            slug={oppSlug}
            runId={runId}
            skill={step.skill_name}
            skillDisplayName={step.display_name}
          />
        ) : (
          <StepChatPane
            slug={oppSlug}
            runId={runId}
            skill={step.skill_name}
            skillDisplayName={step.display_name}
          />
        )}
      </div>
    </aside>
  );
}
