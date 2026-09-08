import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { aceRuns, listActiveRuns, type ActiveRun } from "@/canopy/api";
import { useCanopyStatus } from "@/canopy/useCanopyStatus";

/**
 * The runs ACE is executing RIGHT NOW, and a way into each.
 *
 * ace-web's Sessions list shows only sessions ace-web itself created
 * (`source=ace-web` + this workspace's `origin_key`). A run started any other
 * way — an inbound email ringing the runner, a scheduled turn, a local emdash
 * session — never appeared anywhere here. Those are precisely the runs someone
 * wants to watch, which is why this reads canopy's harness feed instead.
 *
 * Each row links to the EXISTING chat view. That is the whole point: the live
 * viewer, the socket and the ability to type into a run when it stops already
 * work — discovery was the missing half, not the display.
 */
export function ActiveRuns({ workspaceSlug }: { workspaceSlug: string }) {
  const status = useCanopyStatus();
  const base = status?.base_url ?? "";
  const enabled = status?.enabled ?? false;
  const [runs, setRuns] = useState<ActiveRun[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const load = () => {
      listActiveRuns(base)
        .then((all) => { if (!cancelled) { setRuns(aceRuns(all)); setFailed(false); } })
        .catch(() => { if (!cancelled) setFailed(true); });
    };
    load();
    // A run's whole point is that it is moving. Poll rather than leave a stale
    // list on screen; 15s is well under the runner's own ~10s report cadence
    // being useful, and cheap enough for a list this small.
    const t = window.setInterval(load, 15_000);
    return () => { cancelled = true; window.clearInterval(t); };
  }, [base, enabled]);

  if (!enabled) return null;
  // Absence is not failure, and the two must not look the same: "nothing is
  // running" is the ordinary state and should read as calm, while a broken
  // feed needs to say so rather than silently render an empty list.
  if (failed) {
    return (
      <section className="border-b border-border px-6 py-3" data-testid="active-runs">
        <p className="text-sm text-destructive">
          Couldn&rsquo;t load active runs from canopy.
        </p>
      </section>
    );
  }
  if (runs === null) {
    return (
      <section className="border-b border-border px-6 py-3" data-testid="active-runs">
        <p className="text-sm text-muted-foreground">Loading active runs…</p>
      </section>
    );
  }

  return (
    <section className="border-b border-border px-6 py-3" data-testid="active-runs">
      <div className="mb-2 flex items-center gap-2">
        <span className="relative flex h-2 w-2" aria-hidden="true">
          {runs.length > 0 && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
          )}
          <span
            className={`relative inline-flex h-2 w-2 rounded-full ${
              runs.length > 0 ? "bg-emerald-500" : "bg-muted-foreground/40"
            }`}
          />
        </span>
        <h2 className="text-sm font-semibold">Active runs</h2>
        <span className="text-xs text-muted-foreground" data-testid="active-runs-count">
          {runs.length === 0 ? "nothing running" : `${runs.length} running`}
        </span>
      </div>

      {runs.length > 0 && (
        <ul className="flex flex-col gap-1">
          {runs.map((r) => (
            <li key={r.id}>
              <Link
                to={`/w/${workspaceSlug}/chat/c/${r.id}`}
                data-testid="active-run"
                data-run-id={r.id}
                className="flex items-baseline gap-3 rounded-md px-2 py-1.5 hover:bg-muted"
              >
                <span className="truncate font-medium text-foreground">
                  {r.task || "(untitled run)"}
                </span>
                {r.runner_name && (
                  <span className="shrink-0 text-xs text-muted-foreground">
                    on {r.runner_name}
                  </span>
                )}
                {/* What it is DOING, not just that it exists — the difference
                    between a list you check and a list you ignore. */}
                {r.latest_message && (
                  <span className="truncate text-xs text-muted-foreground">
                    {r.latest_message.replace(/\s+/g, " ").slice(0, 120)}
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
