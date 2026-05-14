import { apiV2 } from "./client.v2";
import type { components } from "./generated";

type ActivityFeedOut = components["schemas"]["ActivityFeedOut"];
type ActivityEntryOut = components["schemas"]["ActivityEntryOut"];

export type ActivityKind = "chat" | "verdict";

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
  /** Workspace slug — required for v2 workspace-scoped endpoint. */
  workspaceSlug: string;
  /** Limit to one opp slug. Omit for workspace-wide. */
  opp?: string;
  /** Comma-separated kinds. Omit to include all. */
  type?: ActivityKind | ActivityKind[];
  limit?: number;
}

function mapEntry(e: ActivityEntryOut): ActivityEvent {
  return {
    kind: e.kind,
    ts: e.ts,
    opp_slug: e.opp_slug ?? null,
    step_skill: e.step_skill ?? null,
    title: e.title,
    session_slug: e.session_slug ?? undefined,
    meta: e.meta as Record<string, unknown>,
  };
}

export const fetchActivityFeed = async (params: ActivityFeedParams): Promise<ActivityFeedPage> => {
  const typeParam = params.type
    ? Array.isArray(params.type)
      ? params.type.join(",")
      : params.type
    : undefined;

  const { response, error } = await apiV2.GET("/api/v2/w/{workspace_slug}/activity", {
    params: {
      path: { workspace_slug: params.workspaceSlug },
      query: {
        ...(params.opp ? { opp: params.opp } : {}),
        ...(typeParam ? { type: typeParam } : {}),
        ...(params.limit ? { limit: params.limit } : {}),
      },
    },
  });

  if (error) throw new Error((error as { title?: string }).title || "Failed to fetch activity feed");
  if (!response.ok) throw new Error(`Failed to fetch activity feed: ${response.status}`);
  const out = (await response.json()) as ActivityFeedOut;
  return {
    items: out.items.map(mapEntry),
    total: out.total,
  };
};
