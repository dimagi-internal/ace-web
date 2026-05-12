import { Link, useParams } from "react-router-dom";
import { ExternalLink } from "lucide-react";

interface Props {
  oppSlug: string;
  oppRunId: string;
  oppStepSkill: string;
  /** Human display name from OppWorkspace; falls back to oppSlug when empty. */
  oppDisplayName?: string;
  /** Human display name for oppStepSkill from the plugin SKILL.md
   *  metadata; falls back to oppStepSkill when empty. */
  oppStepSkillDisplay?: string;
}

/**
 * Renders a small breadcrumb above the chat title when the session is
 * linked to an opp + step. Hidden when oppSlug is empty.
 *
 * The opp side has a "linked chats" panel for the inverse direction
 * (apps/opps → which chats discuss this step). This component closes
 * the asymmetry: from inside a chat, the user can now see what opp +
 * step they're discussing and click straight back to the Workbench.
 *
 * Sprint 2: prefer oppDisplayName (from OppWorkspace) over oppSlug.
 */
export function OppHeaderBreadcrumb({
  oppSlug,
  oppRunId,
  oppStepSkill,
  oppDisplayName,
  oppStepSkillDisplay,
}: Props) {
  const { workspaceSlug } = useParams<{ workspaceSlug?: string }>();

  if (!oppSlug) return null;

  const slug = encodeURIComponent(oppSlug);
  const runSeg = oppRunId ? encodeURIComponent(oppRunId) : oppRunId;
  const stepSeg = oppStepSkill ? encodeURIComponent(oppStepSkill) : oppStepSkill;
  const stepHref = workspaceSlug
    ? `/w/${workspaceSlug}/opps/${slug}/runs/${runSeg}/steps/${stepSeg}`
    : `/opps/${slug}/runs/${runSeg}/steps/${stepSeg}`;
  const oppHref = workspaceSlug
    ? `/w/${workspaceSlug}/opps/${slug}`
    : `/opps/${slug}`;
  const oppLabel = oppDisplayName?.trim() || oppSlug;
  const stepLabel = oppStepSkillDisplay?.trim() || oppStepSkill;

  return (
    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span>Discussing</span>
      <Link
        to={oppHref}
        className="font-medium text-foreground hover:underline"
        title={oppDisplayName && oppDisplayName !== oppSlug ? oppSlug : undefined}
      >
        {oppLabel}
      </Link>
      {oppStepSkill ? (
        <>
          <span>·</span>
          <Link
            to={stepHref}
            className="inline-flex items-center gap-1 text-foreground hover:underline"
            title={stepLabel !== oppStepSkill ? oppStepSkill : undefined}
          >
            {stepLabel}
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </Link>
        </>
      ) : null}
    </div>
  );
}
