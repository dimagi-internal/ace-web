import { useEffect, useState } from "react";

import { listRunClones, type RunClone } from "@/api/opps";

/**
 * On a SOURCE run, say where it has been cloned (clone-to-new-workspace) and
 * whether its public summary link now forwards to the clone — so an internal
 * user doesn't keep sending a link that lands somewhere else, or edit a run a
 * partner is reviewing a copy of. Shown only on the source: the clone's own
 * members (possibly outside reviewers) are not told where it came from.
 */
export function ClonedToBanner({
  workspaceSlug,
  slug,
  runId,
}: {
  workspaceSlug: string;
  slug: string;
  runId: string;
}) {
  const [clones, setClones] = useState<RunClone[]>([]);

  useEffect(() => {
    let cancelled = false;
    setClones([]);
    if (!workspaceSlug || !slug || !runId) return;
    listRunClones(workspaceSlug, slug, runId)
      .then((rows) => {
        if (!cancelled) setClones(rows.filter((c) => c.status !== "error"));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug, slug, runId]);

  if (clones.length === 0) return null;
  return (
    <div className="border-b border-border bg-muted/40 px-6 py-2 text-xs text-muted-foreground">
      {clones.map((c) => (
        <p key={c.id}>
          Copied to workspace{" "}
          <a
            className="font-medium text-foreground underline"
            href={`/ace/w/${encodeURIComponent(c.target_workspace)}/opps/${encodeURIComponent(
              c.opp_slug,
            )}?run_id=${encodeURIComponent(c.run_id)}`}
          >
            {c.target_workspace}
          </a>
          {c.status === "copying" ? " (copy in progress)" : ""}.{" "}
          {c.forwards_public_link
            ? "This run's public summary link now opens that copy."
            : "Changes here do not reach the copy."}
        </p>
      ))}
    </div>
  );
}
