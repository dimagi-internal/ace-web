/**
 * Typed client for the workspace-scoped Slack endpoints.
 *
 * Backend: apps/slack/api.py mounted at /api/w/<workspace_slug>/slack/.
 */
import { apiClient } from "./apiClient";
import type { components } from "./generated";

export type SlackStatus = components["schemas"]["SlackStatusOut"];
export type SlackChannel = components["schemas"]["SlackChannelOut"];
export type SlackChannels = components["schemas"]["SlackChannelsOut"];
export type SlackThread = components["schemas"]["SlackThreadOut"];
export type SlackPushInfo = components["schemas"]["SlackPushInfoOut"];
export type SlackPushPhasePayload =
  components["schemas"]["SlackPushPhaseIn"];
export type SlackPushPhaseResult =
  components["schemas"]["SlackPushPhaseOut"];

function problemMessage(err: unknown): string {
  if (err && typeof err === "object" && "title" in err) {
    const e = err as { title?: string; detail?: string };
    return e.detail || e.title || "Request failed";
  }
  return "Request failed";
}

export async function getSlackStatus(workspaceSlug: string): Promise<SlackStatus> {
  const { data, error } = await apiClient.GET(
    "/api/w/{workspace_slug}/slack/status",
    { params: { path: { workspace_slug: workspaceSlug } } },
  );
  if (error) throw new Error(problemMessage(error));
  return data as unknown as SlackStatus;
}

export async function listSlackChannels(workspaceSlug: string): Promise<SlackChannels> {
  const { data, error } = await apiClient.GET(
    "/api/w/{workspace_slug}/slack/channels",
    { params: { path: { workspace_slug: workspaceSlug } } },
  );
  if (error) throw new Error(problemMessage(error));
  return data as unknown as SlackChannels;
}

export async function getSlackPushInfo(
  workspaceSlug: string,
  oppSlug: string,
  runId: string,
): Promise<SlackPushInfo> {
  const { data, error } = await apiClient.GET(
    "/api/w/{workspace_slug}/slack/push-info",
    {
      params: {
        path: { workspace_slug: workspaceSlug },
        query: { opp: oppSlug, run: runId },
      },
    },
  );
  if (error) throw new Error(problemMessage(error));
  return data as unknown as SlackPushInfo;
}

export async function pushPhaseToSlack(
  workspaceSlug: string,
  payload: SlackPushPhasePayload,
): Promise<SlackPushPhaseResult> {
  const { data, error } = await apiClient.POST(
    "/api/w/{workspace_slug}/slack/push-phase",
    {
      params: { path: { workspace_slug: workspaceSlug } },
      body: payload,
    },
  );
  if (error) throw new Error(problemMessage(error));
  return data as unknown as SlackPushPhaseResult;
}
