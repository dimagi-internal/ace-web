/**
 * Archived runs — the one place archived runs still show.
 *
 * Archiving only hides a run from the workbench's default views (opp list,
 * Runs tab, activity). Drive and the run's public summary are untouched, so
 * every row here still links to the run; "Unarchive" puts it back.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";

import { type ArchivedRun, listArchivedRuns, unarchiveOppRun } from "@/api/opps";
import { dropOpp } from "@/api/oppCache";
import { relativeTime } from "@/lib/relativeTime";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; runs: ArchivedRun[] };

export default function ArchivedRunsPage() {
  const { workspaceSlug = "" } = useParams<{ workspaceSlug?: string }>();
  const [state, setState] = useState<State>({ kind: "loading" });

  const load = useCallback(() => {
    listArchivedRuns(workspaceSlug)
      .then((runs) => setState({ kind: "loaded", runs }))
      .catch((e) => setState({ kind: "error", message: e instanceof Error ? e.message : String(e) }));
  }, [workspaceSlug]);

  useEffect(load, [load]);

  const unarchive = async (r: ArchivedRun) => {
    try {
      await unarchiveOppRun(workspaceSlug, r.opp_slug, r.run_id);
      dropOpp(r.opp_slug);
      toast.success(`Unarchived ${r.opp_slug} ${r.run_id}`);
      load();
    } catch (e) {
      toast.error(`Unarchive failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-border bg-card px-6 py-4">
        <h1 className="text-xl font-semibold text-foreground">Archived runs</h1>
        <span className="text-sm text-muted-foreground">
          Hidden from the opp list, Runs tab and activity. Nothing is deleted.
        </span>
        <Link
          to={`/w/${workspaceSlug}/opps`}
          className="ml-auto text-sm text-muted-foreground underline hover:text-foreground"
        >
          Back to opportunities
        </Link>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {state.kind === "loading" && (
          <p className="px-6 py-4 text-sm text-muted-foreground">Loading…</p>
        )}
        {state.kind === "error" && (
          <p className="px-6 py-4 text-sm text-destructive">Could not load: {state.message}</p>
        )}
        {state.kind === "loaded" && state.runs.length === 0 && (
          <p className="px-6 py-4 text-sm text-muted-foreground">No archived runs.</p>
        )}
        {state.kind === "loaded" && state.runs.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                <th className="px-6 py-2">Opportunity</th>
                <th className="px-3 py-2">Run</th>
                <th className="px-3 py-2">Archived</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {state.runs.map((r) => (
                <tr key={`${r.opp_slug}/${r.run_id}`} className="border-b border-border/50 hover:bg-accent/30">
                  <td className="px-6 py-2 font-mono text-xs">{r.opp_slug}</td>
                  <td className="px-3 py-2 font-mono text-xs">
                    <Link
                      to={`/w/${workspaceSlug}/opps/${encodeURIComponent(r.opp_slug)}/runs/${encodeURIComponent(r.run_id)}`}
                      className="hover:underline"
                    >
                      {r.run_id}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">
                    {relativeTime(r.archived_at)}
                    {r.archived_by ? ` by ${r.archived_by}` : ""}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => unarchive(r)}
                      className="rounded border border-border px-2 py-0.5 text-xs text-muted-foreground hover:border-foreground/40 hover:text-foreground"
                    >
                      Unarchive
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
