import { request } from "./client";
import type {
  CreateOppPayload,
  CreateOppResponse,
  DiscussResponse,
  LinkedChat,
  OppCard,
  OppSnapshot,
  StepDetail,
  WorkingSessionResponse,
} from "./types";

export function listOpps(tags?: string[]): Promise<OppCard[]> {
  const q = tags && tags.length > 0
    ? `?tags=${encodeURIComponent(tags.join(","))}`
    : "";
  return request<OppCard[]>(`/opps/${q}`);
}

export function createOpp(payload: CreateOppPayload): Promise<CreateOppResponse> {
  return request<CreateOppResponse>("/opps/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteOpp(slug: string): Promise<void> {
  return request<void>(`/opps/${encodeURIComponent(slug)}`, {
    method: "DELETE",
  });
}

export function updateOppTags(slug: string, tags: string[]): Promise<{ slug: string; tags: string[] }> {
  return request<{ slug: string; tags: string[] }>(
    `/opps/${encodeURIComponent(slug)}`,
    { method: "PATCH", body: JSON.stringify({ tags }) },
  );
}

export function getOpp(slug: string, runId?: string): Promise<OppSnapshot> {
  const q = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  return request<OppSnapshot>(`/opps/${encodeURIComponent(slug)}${q}`);
}

export function getStepDetail(
  slug: string,
  runId: string,
  skill: string,
): Promise<StepDetail> {
  return request<StepDetail>(
    `/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(skill)}`,
  );
}

export function getLinkedChats(
  slug: string,
  runId: string,
  skill: string,
): Promise<LinkedChat[]> {
  return request<LinkedChat[]>(
    `/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(skill)}/chats`,
  );
}

export function discussStep(
  slug: string,
  runId: string,
  skill: string,
): Promise<DiscussResponse> {
  return request<DiscussResponse>(
    `/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(skill)}/discuss`,
    { method: "POST" },
  );
}

export function getWorkingSession(slug: string): Promise<WorkingSessionResponse> {
  return request<WorkingSessionResponse>(
    `/opps/${encodeURIComponent(slug)}/working-session`,
  );
}

export function artifactBodyUrl(
  slug: string,
  runId: string,
  skill: string,
  artifactName: string,
): string {
  // Prepend Vite's BASE_URL so this raw-fetch helper lands on the same
  // /ace/ prefix the rest of the API uses via apiFetch. Without this,
  // prod fetches went to labs.connect.dimagi.com/api/... instead of
  // /ace/api/..., which nginx refuses to route and the artifact body
  // preview showed "Error: 404".
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  return (
    `${base}/api/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}` +
    `/steps/${encodeURIComponent(skill)}/artifacts/${encodeURIComponent(artifactName)}`
  );
}

export function writeArtifact(
  slug: string, runId: string, skill: string, artifactName: string, content: string,
): Promise<{ ok: true }> {
  return request(
    `/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}` +
    `/steps/${encodeURIComponent(skill)}/artifacts/${encodeURIComponent(artifactName)}/write`,
    { method: "PUT", body: JSON.stringify({ content }) },
  );
}

export interface ActionPayload {
  skill: string;
  reason?: string;
}

export function runAction(
  slug: string, runId: string, action: string, payload: ActionPayload,
): Promise<{ message_id: number; turn_index: number }> {
  return request(
    `/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}/actions/${action}`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
