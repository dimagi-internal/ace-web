/**
 * Review-mode "gates pending" banner.
 *
 * In ``--mode review`` the ACE orchestrator pauses at 5 gates (idea-to-pdd,
 * app-deploy, llo-invite, ocs-chatbot-eval-deep, llo-launch) and writes a
 * ``gate-briefs/<skill>.md`` with a checklist + concerns. This banner
 * surfaces any currently-pending gates at the top of the Workbench so an
 * admin can see "something's waiting on me" without hunting through skills.
 *
 * Clicking a chip selects that step in the Workbench so the admin can
 * read the gate brief and approve/reject inline via the ActionButtons.
 */
import { AlertTriangle } from "lucide-react";

import type { Step } from "../../api/types";

interface Props {
  steps: Step[];
  onSelect: (skill: string) => void;
}

export function PendingGatesBanner({ steps, onSelect }: Props) {
  const pending = steps.filter((s) => s.status === "gate-pending");
  if (pending.length === 0) return null;

  return (
    <div className="flex items-center gap-2 border-b border-amber-500/30 bg-amber-500/10 px-4 py-1.5 text-xs">
      <AlertTriangle className="h-3.5 w-3.5 text-amber-500" aria-hidden />
      <span className="font-medium text-amber-700 dark:text-amber-300">
        {pending.length === 1
          ? "1 gate awaiting review"
          : `${pending.length} gates awaiting review`}
      </span>
      <span className="flex flex-wrap gap-1.5">
        {pending.map((s) => (
          <button
            key={s.skill_name}
            type="button"
            onClick={() => onSelect(s.skill_name)}
            className="rounded bg-amber-500/20 px-2 py-0.5 font-mono text-[11px] text-amber-700 hover:bg-amber-500/30 dark:text-amber-200"
            title={`Review gate for ${s.skill_name}`}
          >
            {s.skill_name}
          </button>
        ))}
      </span>
    </div>
  );
}
