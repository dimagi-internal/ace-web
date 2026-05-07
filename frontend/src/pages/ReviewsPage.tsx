import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, ArrowRight, RefreshCw } from "lucide-react";

import { listPendingReviews } from "@/api/workspaces";
import type { PendingReview } from "@/api/types";
import { Button } from "@/components/ui/button";

/**
 * Workspace-level gate review queue. Lists every gate-pending step
 * across the workspace's opps so a reviewer can triage in one place
 * instead of clicking into each opp individually.
 *
 * Click into a row → opp workbench step detail (which is where the
 * Approve / Reject buttons already live; no change there yet).
 */
export default function ReviewsPage() {
  const { workspaceSlug = "" } = useParams();
  const [pending, setPending] = useState<PendingReview[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const navigate = useNavigate();

  const load = (force = false) => {
    setError(null);
    setRefreshing(force);
    listPendingReviews(workspaceSlug, { force })
      .then((d) => setPending(d.pending))
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setRefreshing(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceSlug]);

  if (error) {
    return (
      <div className="p-6 text-sm text-destructive">
        Couldn't load pending reviews: {error}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">
            Pending reviews
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Every gate awaiting human approval, across all opps in this
            workspace.
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => load(true)}
          disabled={refreshing}
        >
          <RefreshCw
            className={`mr-1.5 h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`}
          />
          {refreshing ? "Refreshing…" : "Refresh"}
        </Button>
      </header>

      {pending === null ? (
        <div className="text-sm text-muted-foreground">Loading…</div>
      ) : pending.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-8 text-center">
          <div className="text-4xl">🎉</div>
          <p className="mt-2 text-sm text-foreground">
            No gates awaiting review. Nice work.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {Object.entries(groupByOpp(pending)).map(([slug, rows]) => (
            <li key={slug}>
              <div className="mb-1 flex items-baseline justify-between">
                <Link
                  to={`/w/${workspaceSlug}/opps/${slug}`}
                  className="text-sm font-medium text-foreground hover:underline"
                >
                  {rows[0].opp_display_name || slug}
                </Link>
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  {rows.length} pending
                </span>
              </div>
              <ul className="divide-y divide-border rounded-lg border border-border bg-card">
                {rows.map((r) => (
                  <li key={`${r.opp_slug}-${r.skill_name}`}>
                    <button
                      type="button"
                      onClick={() =>
                        navigate(
                          `/w/${workspaceSlug}/opps/${r.opp_slug}/runs/${r.run_id}/steps/${r.skill_name}`,
                        )
                      }
                      className="flex w-full items-center gap-3 px-3 py-2.5
                        text-left hover:bg-accent"
                    >
                      <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm text-foreground">
                          {r.skill_name}
                        </div>
                        <div className="truncate text-[10px] text-muted-foreground">
                          {r.phase} · run {r.run_id}
                          {r.score !== null && (
                            <span className="ml-2">
                              · judge {Math.round(r.score)}/100
                            </span>
                          )}
                        </div>
                      </div>
                      <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                    </button>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function groupByOpp(rows: PendingReview[]): Record<string, PendingReview[]> {
  const out: Record<string, PendingReview[]> = {};
  for (const r of rows) {
    (out[r.opp_slug] ??= []).push(r);
  }
  return out;
}
