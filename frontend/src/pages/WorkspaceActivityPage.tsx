/**
 * Workspace Activity — "what's running across the workspace right now?"
 *
 * Co-equal surface with Slack's `/ace activity`. Observable facts only:
 * we render timestamps as deltas and source as a fact ("ace-web" /
 * "Drive only"), never claim a plugin is alive.
 *
 * Spec: docs/specs/2026-05-16-workspace-activity-view-design.md.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  type ActivityRow,
  fetchWorkspaceActivity,
  type WorkspaceActivityResponse,
} from "@/api/workspaceActivity";

const REFRESH_MS = 30_000;

export default function WorkspaceActivityPage() {
  const { workspaceSlug } = useParams<{ workspaceSlug: string }>();
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "loaded"; data: WorkspaceActivityResponse; loadedAt: number }
    | { kind: "error"; message: string }
  >({ kind: "loading" });
  const [includeCompleted, setIncludeCompleted] = useState(true);
  const [nowTick, setNowTick] = useState(() => Date.now());

  const load = useCallback(async () => {
    if (!workspaceSlug) return;
    try {
      const data = await fetchWorkspaceActivity({
        workspaceSlug,
        includeCompleted,
      });
      setState({ kind: "loaded", data, loadedAt: Date.now() });
    } catch (e) {
      setState({ kind: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }, [workspaceSlug, includeCompleted]);

  // Initial + filter-toggle load.
  useEffect(() => {
    setState({ kind: "loading" });
    void load();
  }, [load]);

  // Auto-refresh.
  useEffect(() => {
    const t = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(t);
  }, [load]);

  // Tick for "N ago" labels.
  useEffect(() => {
    const t = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="px-6 py-6">
      <header className="mb-4 flex items-baseline justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Activity</h1>
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={includeCompleted}
              onChange={(e) => setIncludeCompleted(e.target.checked)}
            />
            Include recently completed
          </label>
          {state.kind === "loaded" && (
            <span>
              Refreshed {formatDelta(nowTick - state.loadedAt)} ago
            </span>
          )}
          <button
            type="button"
            onClick={() => void load()}
            className="text-foreground hover:underline"
          >
            ↻ Refresh
          </button>
        </div>
      </header>

      {state.kind === "loading" && (
        <p className="text-sm text-muted-foreground">Loading…</p>
      )}
      {state.kind === "error" && (
        <p className="text-sm text-red-500">Couldn’t load activity: {state.message}</p>
      )}
      {state.kind === "loaded" && state.data.rows.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No {includeCompleted ? "recent" : "active"} runs.
        </p>
      )}
      {state.kind === "loaded" && state.data.rows.length > 0 && (
        <ActivityTable
          rows={state.data.rows}
          serverNow={state.data.server_now}
          clientNowMs={nowTick}
          workspaceSlug={workspaceSlug ?? ""}
        />
      )}
    </div>
  );
}

interface TableProps {
  rows: ActivityRow[];
  serverNow: string;
  clientNowMs: number;
  workspaceSlug: string;
}

function ActivityTable({ rows, serverNow, clientNowMs }: TableProps) {
  // Compute the server-relative "now" so all rows agree on the delta
  // regardless of client-clock skew. (We use the page-load delta from
  // the server's reported time.)
  const serverNowMs = useMemo(() => Date.parse(serverNow), [serverNow]);
  const skew = serverNowMs - clientNowMs;

  return (
    <table className="w-full border-collapse text-sm">
      <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
        <tr className="border-b border-border">
          <th className="py-2 pr-4 font-medium">Opp</th>
          <th className="py-2 pr-4 font-medium">Run</th>
          <th className="py-2 pr-4 font-medium">State</th>
          <th className="py-2 pr-4 font-medium">Source</th>
          <th className="py-2 pr-4 font-medium">Last update</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const lastMs = r.last_activity_at ? Date.parse(r.last_activity_at) : null;
          const ageMs = lastMs !== null ? clientNowMs + skew - lastMs : null;
          const ageOpacity = computeAgeOpacity(ageMs);
          return (
            <tr
              key={`${r.opp_slug}:${r.run_id}`}
              className="border-b border-border/60 align-top"
              style={{ opacity: ageOpacity }}
            >
              <td className="py-3 pr-4">
                <Link
                  to={r.phase_url.replace(/^https?:\/\/[^/]+/, "")}
                  className="font-medium text-foreground hover:underline"
                >
                  {r.opp_display_name}
                </Link>
                <div className="text-xs text-muted-foreground">{r.opp_slug}</div>
              </td>
              <td className="py-3 pr-4 font-mono text-xs text-muted-foreground">
                {r.run_id}
              </td>
              <td className="py-3 pr-4">
                <StateCell row={r} />
              </td>
              <td className="py-3 pr-4 text-xs text-muted-foreground">
                {r.source_hint === "ace-web" ? (
                  <span>
                    ace-web
                    {r.source_actor_email && (
                      <span className="block text-[10px]">{r.source_actor_email}</span>
                    )}
                  </span>
                ) : (
                  <span>Drive only</span>
                )}
              </td>
              <td className="py-3 pr-4 text-xs text-muted-foreground tabular-nums">
                {ageMs !== null ? `${formatDelta(ageMs)} ago` : "—"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function StateCell({ row }: { row: ActivityRow }) {
  if (row.current_phase_display || row.current_phase_name) {
    return (
      <div>
        <div className="text-foreground">
          {row.current_phase_display ?? row.current_phase_name}
        </div>
        {(row.current_step_display ?? row.current_step_name) && (
          <div className="font-mono text-[11px] text-muted-foreground">
            {row.current_step_display ?? row.current_step_name}
          </div>
        )}
      </div>
    );
  }
  if (row.lifecycle_status === "complete") {
    return <span className="text-emerald-600">✓ Complete</span>;
  }
  if (row.lifecycle_status === "qa-failed") {
    return <span className="text-amber-600">⚠ qa-failed</span>;
  }
  return <span className="text-muted-foreground">{row.lifecycle_status}</span>;
}

function computeAgeOpacity(ageMs: number | null): number {
  if (ageMs === null) return 1;
  // Bright while within 5min, fade towards 0.5 between 5m and 1h, then
  // stay at 0.5 for older rows. We never hide rows — let the user see
  // everything.
  if (ageMs < 5 * 60_000) return 1;
  if (ageMs > 60 * 60_000) return 0.5;
  const t = (ageMs - 5 * 60_000) / (55 * 60_000);
  return 1 - 0.5 * t;
}

function formatDelta(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}
