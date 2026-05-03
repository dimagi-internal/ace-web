import { apiFetch } from "./client";

export type ActivityKind = "chat" | "verdict" | "gate";

export interface ActivityEvent {
  kind: ActivityKind;
  /** ISO-8601 UTC. */
  ts: string;
  opp_slug: string | null;
  step_skill: string | null;
  title: string;
  /** Only present for chat events. */
  session_slug?: string;
  meta: Record<string, unknown>;
}

export interface ActivityFeedPage {
  items: ActivityEvent[];
  total: number;
}

export interface ActivityFeedParams {
  /** Limit to one opp slug. Omit for workspace-wide. */
  opp?: string;
  /** Comma-separated kinds. Omit to include all three. */
  type?: ActivityKind | ActivityKind[];
  limit?: number;
}

export const fetchActivityFeed = (params: ActivityFeedParams = {}) => {
  const qs = new URLSearchParams();
  if (params.opp) qs.set("opp", params.opp);
  if (params.type) {
    const t = Array.isArray(params.type) ? params.type.join(",") : params.type;
    qs.set("type", t);
  }
  if (params.limit) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs}` : "";
  return apiFetch<ActivityFeedPage>(`/api/activity/${suffix}`);
};
