import { request, requestWithEtag } from "./client";
import { getCachedSnapshot, setCachedSnapshot, getCachedList, setCachedList } from "./oppCache";
import type {
  CreateOppPayload,
  CreateOppResponse,
  DiscussResponse,
  LinkedChat,
  MultiRunSummary,
  OppCard,
  OppCompare,
  OppSnapshot,
  RunSummary,
  Scorecard,
  StepDetail,
  WorkingSessionResponse,
} from "./types.ws";

export async function listOpps(
  tags?: string[],
  opts?: { force?: boolean },
): Promise<OppCard[]> {
  const params = new URLSearchParams();
  if (tags && tags.length > 0) params.set("tags", tags.join(","));
  if (opts?.force) params.set("force", "1");
  const q = params.toString();
  const path = `/opps/${q ? `?${q}` : ""}`;

  const cacheKey = `tags=${(tags ?? []).join(",")}`;
  const cached = !opts?.force ? getCachedList(cacheKey) : undefined;
  const headers: HeadersInit = cached ? { "If-None-Match": cached.etag } : {};

  const res = await requestWithEtag<OppCard[]>(path, { headers });
  if (res.status === 304 && cached) return cached.data;
  if (res.data) {
    setCachedList(cacheKey, { data: res.data, etag: res.etag });
    return res.data;
  }
  throw new Error("listOpps: unexpected empty response without cache");
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

export async function getOpp(
  slug: string,
  runId?: string,
  opts?: { force?: boolean },
): Promise<OppSnapshot> {
  const params = new URLSearchParams();
  if (runId) params.set("run_id", runId);
  if (opts?.force) params.set("force", "1");
  const q = params.toString();
  const path = `/opps/${encodeURIComponent(slug)}${q ? `?${q}` : ""}`;

  const cached = !opts?.force ? getCachedSnapshot(slug, runId ?? null) : undefined;
  const headers: HeadersInit = cached ? { "If-None-Match": cached.etag } : {};

  const res = await requestWithEtag<OppSnapshot>(path, { headers });
  if (res.status === 304 && cached) return cached.data;
  if (res.data) {
    setCachedSnapshot(slug, runId ?? null, { data: res.data, etag: res.etag });
    return res.data;
  }
  throw new Error("getOpp: unexpected empty response without cache");
}


export function getOppCompare(slugA: string, slugB: string): Promise<OppCompare> {
  return request<OppCompare>(
    `/opps/compare/${encodeURIComponent(slugA)}/${encodeURIComponent(slugB)}`,
  );
}

export function getScorecard(slug: string): Promise<Scorecard> {
  return request<Scorecard>(`/opps/${encodeURIComponent(slug)}/scorecard`);
}

export function getMultiRunSummary(
  slug: string,
  opts?: { limit?: number; force?: boolean },
): Promise<MultiRunSummary> {
  const params = new URLSearchParams();
  if (opts?.limit) params.set("limit", String(opts.limit));
  if (opts?.force) params.set("force", "1");
  const q = params.toString();
  return request<MultiRunSummary>(
    `/opps/${encodeURIComponent(slug)}/multi-run-summary${q ? `?${q}` : ""}`,
  );
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

export function listOppRuns(slug: string): Promise<RunSummary[]> {
  return request<RunSummary[]>(`/opps/${encodeURIComponent(slug)}/runs`);
}

export function deleteOppRun(slug: string, runId: string): Promise<void> {
  return request<void>(
    `/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}`,
    { method: "DELETE" },
  );
}

export function forkOpp(
  slug: string,
  payload: { fork_at_phase: string; source_run_id?: string | null },
): Promise<{ slug: string; run_id: string; working_session_slug: string }> {
  return request<{ slug: string; run_id: string; working_session_slug: string }>(
    `/opps/${encodeURIComponent(slug)}/fork`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export type ForkProgress =
  | { status: "unknown" | "counting" | "finalizing" }
  | { status: "copying"; copied: number; total: number; current?: string }
  | {
      status: "done";
      copied: number;
      total: number;
      opp_slug: string;
      new_run_id: string;
    }
  | { status: "error"; error: string; code?: string };

export function getForkStatus(
  slug: string,
  sourceRunId: string | null | undefined,
): Promise<ForkProgress> {
  const qs = new URLSearchParams({
    source_run_id: sourceRunId ?? "",
  }).toString();
  return request<ForkProgress>(
    `/opps/${encodeURIComponent(slug)}/fork/status?${qs}`,
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
