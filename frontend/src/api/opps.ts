import { apiV2 } from "./client.v2";
import { getCachedSnapshot, setCachedSnapshot, getCachedList, setCachedList } from "./oppCache";
import type {
  CreateOppPayload,
  CreateOppResponse,
  DiscussResponse,
  LinkedChat,
  MultiRunSummary,
  OppCard,
  OppSnapshot,
  RunSummary,
  Scorecard,
  StepDetail,
} from "./types.ws";

/**
 * opps.ts — opportunities resource API client (v2).
 *
 * All endpoints are workspace-scoped under /api/w/{workspace_slug}/opps/...
 *
 * Endpoints with NO v2 equivalent throw a descriptive Error so callers
 * fail loudly instead of silently 404-ing:
 *   - getOppCompare (cross-opp compare) — legacy DRF only
 *   - getMultiRunSummary — legacy DRF only (v2 compare is within-opp)
 *   - getLinkedChats — no v2 endpoint
 *   - getWorkingSession — no v2 endpoint
 *   - writeArtifact — no v2 endpoint
 *   - runAction — no v2 endpoint
 */

export async function listOpps(
  workspaceSlug: string,
  tags?: string[],
  opts?: { force?: boolean },
): Promise<OppCard[]> {
  const params = new URLSearchParams();
  if (tags && tags.length > 0) params.set("tags", tags.join(","));
  if (opts?.force) params.set("force", "1");

  const cacheKey = `ws=${workspaceSlug}&tags=${(tags ?? []).join(",")}`;
  const cached = !opts?.force ? getCachedList(cacheKey) : undefined;

  const { response } = await apiV2.GET("/api/w/{workspace_slug}/opps", {
    params: { path: { workspace_slug: workspaceSlug } },
    headers: cached ? { "If-None-Match": cached.etag } : {},
  });

  if (response.status === 304 && cached) return cached.data;
  if (!response.ok) throw new Error(`listOpps: ${response.status}`);

  const etag = response.headers.get("ETag") ?? "";
  // The v2 OppCardOut shape is a subset of what the frontend's OppCard
  // type expects (the frontend type carries legacy DRF fields like
  // display_name/current_step/tags/labels/eval_score). Map field renames
  // and fill missing fields with safe defaults so consumers don't crash
  // on .display_name.toLowerCase() etc.
  const page = (await response.json()) as { items: Array<Record<string, unknown>> };
  const data: OppCard[] = (page.items ?? []).map((raw) => v2ToOppCard(raw));
  setCachedList(cacheKey, { data, etag });
  return data;
}

function v2ToOppCard(raw: Record<string, unknown>): OppCard {
  const s = (v: unknown): string | null => (typeof v === "string" ? v : null);
  return {
    slug: (raw.slug as string) ?? "",
    display_name: (raw.title as string) ?? (raw.slug as string) ?? "",
    labels: [],
    tags: [],
    created_at: s(raw.updated_at),
    created_by: null,
    current_run_id: s(raw.last_run_id),
    current_phase: s(raw.current_phase),
    current_phase_display: s(raw.current_phase),
    current_step: s(raw.current_skill),
    current_step_display: s(raw.current_skill),
    status: "active",
    eval_score: null,
    eval_score_pct: null,
    eval_passed: null,
    last_activity_at: s(raw.updated_at),
    run_count: typeof raw.run_count === "number" ? raw.run_count : 0,
  } as OppCard;
}

export async function createOpp(
  workspaceSlug: string,
  payload: CreateOppPayload,
): Promise<CreateOppResponse> {
  const { response } = await apiV2.POST("/api/w/{workspace_slug}/opps", {
    params: { path: { workspace_slug: workspaceSlug } },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    body: payload as any,
  });
  if (!response.ok) throw new Error(`createOpp: ${response.status}`);
  return (await response.json()) as CreateOppResponse;
}

export async function deleteOpp(workspaceSlug: string, slug: string): Promise<void> {
  const { response } = await apiV2.DELETE("/api/w/{workspace_slug}/opps/{slug}", {
    params: { path: { workspace_slug: workspaceSlug, slug } },
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`deleteOpp: ${response.status}`);
  }
}

export async function updateOppTags(
  workspaceSlug: string,
  slug: string,
  tags: string[],
): Promise<{ slug: string; tags: string[] }> {
  const { response } = await apiV2.PATCH("/api/w/{workspace_slug}/opps/{slug}", {
    params: { path: { workspace_slug: workspaceSlug, slug } },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    body: { tags } as any,
  });
  if (!response.ok) throw new Error(`updateOppTags: ${response.status}`);
  return (await response.json()) as { slug: string; tags: string[] };
}

export async function getOpp(
  workspaceSlug: string,
  slug: string,
  runId?: string,
  opts?: { force?: boolean },
): Promise<OppSnapshot> {
  const cached = !opts?.force ? getCachedSnapshot(slug, runId ?? null) : undefined;

  const { response } = await apiV2.GET("/api/w/{workspace_slug}/opps/{slug}", {
    params: {
      path: { workspace_slug: workspaceSlug, slug },
      query: runId ? { run_id: runId } : {},
    },
    headers: cached ? { "If-None-Match": cached.etag } : {},
  });

  if (response.status === 304 && cached) return cached.data;
  if (!response.ok) throw new Error(`getOpp: ${response.status}`);

  const etag = response.headers.get("ETag") ?? "";
  const data = (await response.json()) as OppSnapshot;
  setCachedSnapshot(slug, runId ?? null, { data, etag });
  return data;
}

/** Cross-opp comparison has no v2 endpoint — will be addressed in a future PR. */
export function getOppCompare(_slugA: string, _slugB: string): Promise<never> {
  return Promise.reject(
    new Error(
      "getOppCompare: cross-opp comparison endpoint not available in v2 — " +
        "see /api/w/{workspace_slug}/opps/{slug}/compare for within-opp run comparison",
    ),
  );
}

export async function getScorecard(workspaceSlug: string, slug: string): Promise<Scorecard> {
  const { response } = await apiV2.GET("/api/w/{workspace_slug}/opps/{slug}/scorecard", {
    params: { path: { workspace_slug: workspaceSlug, slug } },
  });
  if (!response.ok) throw new Error(`getScorecard: ${response.status}`);
  return (await response.json()) as Scorecard;
}

/** Multi-run summary has no v2 equivalent — will be addressed in a future PR. */
export function getMultiRunSummary(
  _slug: string,
  _opts?: { limit?: number; force?: boolean },
): Promise<MultiRunSummary> {
  return Promise.reject(
    new Error(
      "getMultiRunSummary: legacy DRF endpoint removed — no v2 equivalent yet; " +
        "use /api/w/{workspace_slug}/opps/{slug}/compare for within-opp run comparison",
    ),
  );
}

export async function getStepDetail(
  workspaceSlug: string,
  slug: string,
  runId: string,
  skill: string,
): Promise<StepDetail> {
  const { response } = await apiV2.GET("/api/w/{workspace_slug}/opps/{slug}/steps/{skill}", {
    params: {
      path: { workspace_slug: workspaceSlug, slug, skill },
      query: { run_id: runId },
    },
  });
  if (!response.ok) throw new Error(`getStepDetail: ${response.status}`);
  return (await response.json()) as StepDetail;
}

/** getLinkedChats has no v2 endpoint — will be addressed in a future PR. */
export function getLinkedChats(
  _slug: string,
  _runId: string,
  _skill: string,
): Promise<LinkedChat[]> {
  return Promise.reject(
    new Error("getLinkedChats: no v2 endpoint — will be addressed in a future PR"),
  );
}

export async function discussStep(
  workspaceSlug: string,
  slug: string,
  runId: string,
  skill: string,
): Promise<DiscussResponse> {
  const { response } = await apiV2.POST("/api/w/{workspace_slug}/opps/{slug}/actions/seed-chat", {
    params: { path: { workspace_slug: workspaceSlug, slug } },
    body: { step_skill: skill, run_id: runId },
  });
  if (!response.ok) throw new Error(`discussStep: ${response.status}`);
  return (await response.json()) as DiscussResponse;
}

export async function listOppRuns(workspaceSlug: string, slug: string): Promise<RunSummary[]> {
  const { response } = await apiV2.GET("/api/w/{workspace_slug}/opps/{slug}/runs", {
    params: { path: { workspace_slug: workspaceSlug, slug } },
  });
  if (!response.ok) throw new Error(`listOppRuns: ${response.status}`);
  const page = (await response.json()) as { items: RunSummary[] };
  return page.items ?? (page as unknown as RunSummary[]);
}

export async function deleteOppRun(
  workspaceSlug: string,
  slug: string,
  runId: string,
): Promise<void> {
  const { response } = await apiV2.DELETE(
    "/api/w/{workspace_slug}/opps/{slug}/runs/{run_id}",
    { params: { path: { workspace_slug: workspaceSlug, slug, run_id: runId } } },
  );
  if (!response.ok && response.status !== 204) {
    throw new Error(`deleteOppRun: ${response.status}`);
  }
}

export async function forkOpp(
  workspaceSlug: string,
  slug: string,
  payload: { fork_at_phase: string; source_run_id?: string | null },
): Promise<{ slug: string; run_id: string; working_session_slug: string }> {
  const { response } = await apiV2.POST("/api/w/{workspace_slug}/opps/{slug}/fork", {
    params: { path: { workspace_slug: workspaceSlug, slug } },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    body: payload as any,
  });
  if (!response.ok) throw new Error(`forkOpp: ${response.status}`);
  return (await response.json()) as { slug: string; run_id: string; working_session_slug: string };
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

export async function getForkStatus(
  workspaceSlug: string,
  slug: string,
  sourceRunId: string | null | undefined,
): Promise<ForkProgress> {
  const { response } = await apiV2.GET("/api/w/{workspace_slug}/opps/{slug}/fork/status", {
    params: {
      path: { workspace_slug: workspaceSlug, slug },
      query: sourceRunId ? { source_run_id: sourceRunId } : {},
    },
  });
  if (!response.ok) throw new Error(`getForkStatus: ${response.status}`);
  return (await response.json()) as ForkProgress;
}

/** getWorkingSession has no v2 endpoint — will be addressed in a future PR. */
export function getWorkingSession(_slug: string): Promise<never> {
  return Promise.reject(
    new Error("getWorkingSession: no v2 endpoint — will be addressed in a future PR"),
  );
}

export function artifactBodyUrl(
  workspaceSlug: string,
  slug: string,
  runId: string,
  skill: string,
  artifactName: string,
): string {
  // Prepend Vite's BASE_URL so this raw-fetch helper lands on the same
  // /ace/ prefix the rest of the API uses via apiV2. Without this,
  // prod fetches went to labs.connect.dimagi.com/api/... instead of
  // /ace/api/..., which nginx refuses to route and the artifact body
  // preview showed "Error: 404".
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  return (
    `${base}/api/w/${encodeURIComponent(workspaceSlug)}/opps/${encodeURIComponent(slug)}` +
    `/steps/${encodeURIComponent(skill)}/artifacts/${encodeURIComponent(artifactName)}` +
    `?run_id=${encodeURIComponent(runId)}`
  );
}

/** writeArtifact has no v2 endpoint — will be addressed in a future PR. */
export function writeArtifact(
  _workspaceSlug: string,
  _slug: string,
  _runId: string,
  _skill: string,
  _artifactName: string,
  _content: string,
): Promise<never> {
  return Promise.reject(
    new Error("writeArtifact: no v2 endpoint — will be addressed in a future PR"),
  );
}

export interface ActionPayload {
  skill: string;
  reason?: string;
}

/** runAction has no v2 endpoint — will be addressed in a future PR. */
export function runAction(
  _workspaceSlug: string,
  _slug: string,
  _runId: string,
  _action: string,
  _payload: ActionPayload,
): Promise<never> {
  return Promise.reject(
    new Error("runAction: no v2 endpoint — will be addressed in a future PR"),
  );
}
