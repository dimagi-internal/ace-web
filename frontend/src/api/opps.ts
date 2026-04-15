import { request } from "./client";
import type {
  CompareResult,
  CreateOppPayload,
  CreateOppResponse,
  DiscussResponse,
  LinkedChat,
  OppCard,
  OppSnapshot,
  StepDetail,
  WorkingSessionResponse,
} from "./types";

export function listOpps(): Promise<OppCard[]> {
  return request<OppCard[]>("/opps/");
}

export function createOpp(payload: CreateOppPayload): Promise<CreateOppResponse> {
  return request<CreateOppResponse>("/opps/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
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

export function compareRuns(
  slug: string,
  fromRunId: string,
  toRunId: string,
): Promise<CompareResult> {
  const qs = new URLSearchParams({ from: fromRunId, to: toRunId });
  return request<CompareResult>(
    `/opps/${encodeURIComponent(slug)}/compare?${qs.toString()}`,
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
  return (
    `/api/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}` +
    `/steps/${encodeURIComponent(skill)}/artifacts/${encodeURIComponent(artifactName)}`
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
