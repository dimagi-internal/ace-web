/**
 * "What's running across the workspace?" feed.
 *
 * Consumes GET /api/w/{slug}/activity/runs. Hand-typed for now — the
 * generated openapi types catch up next regen cycle.
 *
 * Design principle: observable facts only. We render timestamps and
 * source labels straight from the server; never claim what's "alive".
 * See docs/specs/2026-05-16-workspace-activity-view-design.md.
 */
import { apiClient } from "./apiClient";

export type SourceHint = "ace-web" | "drive-only";

export interface ActivityRow {
  opp_slug: string;
  opp_display_name: string;
  run_id: string;
  last_activity_at: string | null;
  current_phase_name: string | null;
  current_phase_display: string | null;
  current_step_name: string | null;
  current_step_display: string | null;
  lifecycle_status: string;
  last_actor: string | null;
  source_hint: SourceHint;
  source_actor_email: string | null;
  phase_url: string;
}

export interface WorkspaceActivityResponse {
  rows: ActivityRow[];
  /** ISO-8601 UTC. Use to compute "N ago" deltas without client-clock skew. */
  server_now: string;
}

export interface WorkspaceActivityParams {
  workspaceSlug: string;
  /** Default true. When false, completed runs are dropped from the feed. */
  includeCompleted?: boolean;
  /** Default 20, server caps at 100. */
  limit?: number;
}

export const fetchWorkspaceActivity = async (
  params: WorkspaceActivityParams,
): Promise<WorkspaceActivityResponse> => {
  // Bare ``fetch`` (not ``apiClient``) because the endpoint's query
  // params (``include_completed``, ``limit``) aren't declared in
  // ``generated.ts`` yet — the openapi emitter declares
  // ``parameters.query?: never`` for this path. Once the server-side
  // schema declares them, swap to ``apiClient.GET("/api/w/{slug}/activity/runs", ...)``
  // and this whole helper collapses.
  //
  // CRITICAL: the bare URL must include Vite's ``BASE_URL`` prefix.
  // In prod that's ``/ace`` (ace-web is ALB-mounted at ``/ace/*``).
  // Without this, ``fetch("/api/...")`` resolves to
  // ``labs.connect.dimagi.com/api/...`` which is NOT routed to
  // ace-web and 404s. ``apiClient`` handles this automatically; the
  // bare fetch path has to do it manually.
  const baseUrl = (import.meta.env.BASE_URL || "/").replace(/\/$/, "");
  const query = new URLSearchParams();
  if (params.includeCompleted !== undefined) {
    query.set("include_completed", String(params.includeCompleted));
  }
  if (params.limit !== undefined) {
    query.set("limit", String(params.limit));
  }
  const qs = query.toString();
  const url =
    `${baseUrl}/api/w/${encodeURIComponent(params.workspaceSlug)}/activity/runs` +
    (qs ? `?${qs}` : "");
  const resp = await fetch(url, { credentials: "include" });
  if (!resp.ok) {
    throw new Error(`Failed to fetch workspace activity: ${resp.status}`);
  }
  return (await resp.json()) as WorkspaceActivityResponse;
};

// Silence unused-import warning until we swap to apiClient.GET above.
void apiClient;
