import { request } from "./client";
import type {
  CompareResult,
  DiscussResponse,
  LinkedChat,
  OppCard,
  OppSnapshot,
  StepDetail,
} from "./types";

export function listOpps(): Promise<OppCard[]> {
  return request<OppCard[]>("/opps/");
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
