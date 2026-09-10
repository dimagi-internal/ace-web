import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  aceRuns, listActiveRuns, listActiveTurns, liveTurns,
  type ActiveRun, type ActiveTurn,
} from "@/canopy/api";
import { useCanopyStatus } from "@/canopy/useCanopyStatus";
import { TurnWatch } from "./TurnWatch";

/**
 * The runs ACE is executing RIGHT NOW, and a way into each.
 *
 * ace-web's Sessions list shows only sessions ace-web itself created
 * (`source=ace-web` + this workspace's `origin_key`). A run started any other
 * way — an inbound email ringing the runner, a scheduled turn, a local emdash
 * session — never appeared anywhere here. Those are precisely the runs someone
 * wants to watch, which is why this reads canopy's harness feed instead.
 *
 * TWO feeds, because one cannot see the whole fleet:
 *
 *  - SESSIONS (`/api/harness/sessions`) are derived from emdash's sqlite, so
 *    they cover the laptops. Each links to the existing chat view, which is the
 *    better surface: a live socket and a composer to type into a stopped run.
 *  - TURNS (`/api/harness/turns/`) cover everything else, and specifically the
 *    CLOUD runner. It has no emdash, reports `sessions=[]` on every heartbeat,
 *    and so never appears in the first feed at all — which is how the inbound
 *    email path, whose routing rules deliberately pin work to that box, ended
 *    up invisible here. It streams a full event ledger per turn regardless, so
 *    those runs are watched inline instead.
 *
 * A turn that drives a listed session is dropped rather than shown twice.
 */
export function ActiveRuns({ workspaceSlug }: { workspaceSlug: string }) {
  const status = useCanopyStatus();
  const base = status?.base_url ?? "";
  const enabled = status?.enabled ?? false;
  const [runs, setRuns] = useState<ActiveRun[] | null>(null);
  const [turns, setTurns] = useState<ActiveTurn[]>([]);
  const [watching, setWatching] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  // The poll closure below outlives any single `watching` value, so it reads the
  // open turn through a ref (ace-web#757).
  const watchingRef = useRef<string | null>(null);
  watchingRef.current = watching;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const load = () => {
      // Independent: a cloud run must still be listed when the sessions feed is
      // unreachable, and vice versa. `allSettled` keeps one broken half from
      // blanking the other — the whole point of reading two feeds.
      Promise.allSettled([listActiveRuns(base), listActiveTurns(base)])
        .then(([s, t]) => {
          if (cancelled) return;
          const sessions = s.status === "fulfilled" ? aceRuns(s.value) : [];
          // `watchingRef`, not `watching`: this closure is created once per
          // [base, enabled] and would otherwise capture the value of `watching`
          // at mount (null), pinning nothing. The ref is read at poll time.
          const turns = t.status === "fulfilled"
            ? liveTurns(t.value, sessions.map((r) => r.id),
                        watchingRef.current ? [watchingRef.current] : [])
            : [];
          setRuns(sessions);
          setTurns(turns);
          setFailed(s.status === "rejected" && t.status === "rejected");
        });
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

  const total = runs.length + turns.length;

  return (
    <section className="border-b border-border px-6 py-3" data-testid="active-runs">
      <div className="mb-2 flex items-center gap-2">
        <span className="relative flex h-2 w-2" aria-hidden="true">
          {total > 0 && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
          )}
          <span
            className={`relative inline-flex h-2 w-2 rounded-full ${
              total > 0 ? "bg-emerald-500" : "bg-muted-foreground/40"
            }`}
          />
        </span>
        <h2 className="text-sm font-semibold">Active runs</h2>
        <span className="text-xs text-muted-foreground" data-testid="active-runs-count">
          {total === 0 ? "nothing running" : `${total} running`}
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

      {turns.length > 0 && (
        <ul className="mt-1 flex flex-col gap-1" data-testid="active-turn-list">
          {turns.map((t) => (
            <li key={t.id}>
              <button
                type="button"
                data-testid="active-turn"
                data-turn-id={t.id}
                aria-expanded={watching === t.id}
                onClick={() => setWatching(watching === t.id ? null : t.id)}
                className="flex w-full items-baseline gap-3 rounded-md px-2 py-1.5 text-left hover:bg-muted"
              >
                <span className="truncate font-medium text-foreground">
                  {firstLine(t.prompt) || "(no prompt)"}
                </span>
                {/* The origin is the useful label here: "email" is why anyone
                    is looking at this list in the first place. */}
                <span className="shrink-0 text-xs text-muted-foreground">
                  {t.origin}{t.runner_name ? ` · on ${t.runner_name}` : ""}
                  {t.status === "queued" ? " · queued" : ""}
                </span>
              </button>
              {watching === t.id && (
                <div className="mt-1 mb-2 ml-2 border-l border-border pl-3">
                  <TurnWatch base={base} turnId={t.id} live={t.status !== "done"} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** A turn's prompt is the whole email/instruction; the list wants a title. */
function firstLine(prompt: string): string {
  const line = prompt.split("\n").find((l) => l.trim()) ?? "";
  return line.trim().slice(0, 100);
}
