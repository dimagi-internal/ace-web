import { Link, useParams } from "react-router-dom";
import { ExternalLink } from "lucide-react";

interface Props {
  oppSlug: string;
  oppRunId: string;
  oppStepSkill: string;
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
 * Display name today is the opp slug — the slug is already the
 * human-readable identifier across the codebase. Lifting to
 * OppWorkspace.display_name is a follow-up.
 */
export function OppHeaderBreadcrumb({
  oppSlug,
  oppRunId,
  oppStepSkill,
}: Props) {
  const { workspaceSlug } = useParams<{ workspaceSlug?: string }>();

  if (!oppSlug) return null;

  const stepHref = workspaceSlug
    ? `/w/${workspaceSlug}/opps/${oppSlug}/runs/${oppRunId}/steps/${oppStepSkill}`
    : `/opps/${oppSlug}/runs/${oppRunId}/steps/${oppStepSkill}`;
  const oppHref = workspaceSlug
    ? `/w/${workspaceSlug}/opps/${oppSlug}`
    : `/opps/${oppSlug}`;

  return (
    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span>Discussing</span>
      <Link
        to={oppHref}
        className="font-medium text-foreground hover:underline"
      >
        {oppSlug}
      </Link>
      {oppStepSkill ? (
        <>
          <span>·</span>
          <Link
            to={stepHref}
            className="inline-flex items-center gap-1 text-foreground hover:underline"
          >
            {oppStepSkill}
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </Link>
        </>
      ) : null}
    </div>
  );
}
