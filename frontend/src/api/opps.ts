import { apiClient } from "./apiClient";
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

  const { data: responseData, response } = await apiClient.GET("/api/w/{workspace_slug}/opps", {
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
  const page = responseData as unknown as { items: Array<Record<string, unknown>> };
  const data: OppCard[] = (page.items ?? []).map((raw) => v2ToOppCard(raw));
  setCachedList(cacheKey, { data, etag });
  return data;
}

/**
 * Normalise a backend timestamp into an ISO string or null.
 *
 * Treats null, missing, empty string, and Unix epoch-zero variants as null.
 * Pre-2026-05-20 the v2 list-opps endpoint serialised opps with no completed
 * run as `updated_at: "1970-01-01T00:00:00Z"`, which the OppCard component
 * happily rendered as `last 12/31/1969` (#466). Even after the backend fix
 * we keep this guard so any stale ETag-cached payload or future regression
 * still renders the empty state instead of a 1969 date.
 */
export function parseTs(v: unknown): string | null {
  if (typeof v !== "string" || v === "") return null;
  const ms = Date.parse(v);
  if (!Number.isFinite(ms) || ms <= 0) return null;
  return v;
}

export function v2ToOppCard(raw: Record<string, unknown>): OppCard {
  const s = (v: unknown): string | null => (typeof v === "string" ? v : null);
  const updated = parseTs(raw.updated_at);
  // runs_summary lives on the main /opps payload (#512) so the
  // OppCardRunsStrip can read phase-chip data from props instead of
  // firing a per-card /opps/<slug>/runs call. Pass through whatever
  // the server sent; default to [] for backward compat with stale
  // ETag-cached payloads from before the field shipped.
  const runs_summary = Array.isArray(raw.runs_summary)
    ? (raw.runs_summary as RunSummary[])
    : [];
  return {
    slug: (raw.slug as string) ?? "",
    display_name: (raw.title as string) ?? (raw.slug as string) ?? "",
    labels: [],
    tags: [],
    created_at: updated,
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
    last_activity_at: updated,
    run_count: typeof raw.run_count === "number" ? raw.run_count : 0,
    runs_summary,
  } as OppCard;
}

export async function createOpp(
  workspaceSlug: string,
  payload: CreateOppPayload,
): Promise<CreateOppResponse> {
  const { data, response } = await apiClient.POST("/api/w/{workspace_slug}/opps", {
    params: { path: { workspace_slug: workspaceSlug } },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    body: payload as any,
  });
  if (!response.ok) throw new Error(`createOpp: ${response.status}`);
  return data as unknown as CreateOppResponse;
}

export async function deleteOpp(workspaceSlug: string, slug: string): Promise<void> {
  const { response } = await apiClient.DELETE("/api/w/{workspace_slug}/opps/{slug}", {
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
  const { data, response } = await apiClient.PATCH("/api/w/{workspace_slug}/opps/{slug}", {
    params: { path: { workspace_slug: workspaceSlug, slug } },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    body: { tags } as any,
  });
  if (!response.ok) throw new Error(`updateOppTags: ${response.status}`);
  return data as unknown as { slug: string; tags: string[] };
}

export async function getOpp(
  workspaceSlug: string,
  slug: string,
  runId?: string,
  opts?: { force?: boolean },
): Promise<OppSnapshot> {
  const cached = !opts?.force ? getCachedSnapshot(slug, runId ?? null) : undefined;

  const { data: responseData, response } = await apiClient.GET("/api/w/{workspace_slug}/opps/{slug}", {
    params: {
      path: { workspace_slug: workspaceSlug, slug },
      query: runId ? { run_id: runId } : {},
    },
    headers: cached ? { "If-None-Match": cached.etag } : {},
  });

  if (response.status === 304 && cached) return cached.data;
  if (!response.ok) throw new Error(`getOpp: ${response.status}`);

  const etag = response.headers.get("ETag") ?? "";
  const data = responseData as unknown as OppSnapshot;
  setCachedSnapshot(slug, runId ?? null, { data, etag });
  return data;
}

/** Cross-opp comparison — restored as /opps/cross-compare/{a}/{b}
 * (distinct from within-opp /opps/{slug}/compare which compares runs of
 * the same opp). */
export async function getOppCompare(
  workspaceSlug: string,
  slugA: string,
  slugB: string,
): Promise<OppCompare> {
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const url = `${base}/api/w/${encodeURIComponent(workspaceSlug)}/opps/cross-compare/${encodeURIComponent(slugA)}/${encodeURIComponent(slugB)}`;
  const resp = await fetch(url, { credentials: "include" });
  if (!resp.ok) throw new Error(`getOppCompare: ${resp.status}`);
  return (await resp.json()) as OppCompare;
}

export async function getScorecard(workspaceSlug: string, slug: string): Promise<Scorecard> {
  const { data, response } = await apiClient.GET("/api/w/{workspace_slug}/opps/{slug}/scorecard", {
    params: { path: { workspace_slug: workspaceSlug, slug } },
  });
  if (!response.ok) throw new Error(`getScorecard: ${response.status}`);
  return data as unknown as Scorecard;
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
  const { data, response } = await apiClient.GET("/api/w/{workspace_slug}/opps/{slug}/steps/{skill}", {
    params: {
      path: { workspace_slug: workspaceSlug, slug, skill },
      query: { run_id: runId },
    },
  });
  if (!response.ok) throw new Error(`getStepDetail: ${response.status}`);
  // No `as unknown as` here: StepDetail is structurally compatible with the
  // generated StepSnapshotOut. The double cast is what let this endpoint's
  // real shape (id/url) drift from what the pane read (drive_file_id/
  // drive_web_link) without the compiler noticing.
  return data as StepDetail;
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
  const { data, response } = await apiClient.POST("/api/w/{workspace_slug}/opps/{slug}/actions/seed-chat", {
    params: { path: { workspace_slug: workspaceSlug, slug } },
    body: { step_skill: skill, run_id: runId },
  });
  if (!response.ok) throw new Error(`discussStep: ${response.status}`);
  return data as unknown as DiscussResponse;
}

export async function listOppRuns(workspaceSlug: string, slug: string): Promise<RunSummary[]> {
  const { data, response } = await apiClient.GET("/api/w/{workspace_slug}/opps/{slug}/runs", {
    params: { path: { workspace_slug: workspaceSlug, slug } },
  });
  if (!response.ok) throw new Error(`listOppRuns: ${response.status}`);
  const page = data as unknown as { items: RunSummary[] };
  return page.items ?? (data as unknown as RunSummary[]);
}

export async function deleteOppRun(
  workspaceSlug: string,
  slug: string,
  runId: string,
): Promise<void> {
  const { response } = await apiClient.DELETE(
    "/api/w/{workspace_slug}/opps/{slug}/runs/{run_id}",
    { params: { path: { workspace_slug: workspaceSlug, slug, run_id: runId } } },
  );
  if (!response.ok && response.status !== 204) {
    throw new Error(`deleteOppRun: ${response.status}`);
  }
}

export type ForkMode = "keep-overrides-only" | "keep-all";

export interface ForkOppBody {
  fork_at_phase: string;
  source_run_id?: string | null;
  edits?: { row_id: string; new_answer: string; override_reasoning?: string }[];
  /**
   * Controls how upstream decisions carry forward:
   *   - "keep-all" (default): every upstream row survives the fork.
   *   - "keep-overrides-only": only rows with status=overridden survive
   *     (AI defaults are dropped so downstream phases re-derive them).
   */
  mode?: ForkMode;
}

export async function forkOpp(
  workspaceSlug: string,
  slug: string,
  payload: ForkOppBody,
): Promise<{ slug: string; run_id: string; working_session_slug: string }> {
  const { data, response } = await apiClient.POST("/api/w/{workspace_slug}/opps/{slug}/fork", {
    params: { path: { workspace_slug: workspaceSlug, slug } },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    body: payload as any,
  });
  if (!response.ok) throw new Error(`forkOpp: ${response.status}`);
  return data as unknown as { slug: string; run_id: string; working_session_slug: string };
}

export interface SavedOverrideRow {
  id: string;
  phase: string;
  question: string;
  ai_default: string;
  override: string;
  override_reasoning?: string;
  decided_by: string;
  decided_at: string;
  source_run_id: string;
}

export interface SaveDecisionOverridesResult {
  file_id: string | null;
  override_count: number;
  /** The complete merged file content after this save. */
  overrides: SavedOverrideRow[];
}

/**
 * Persist the run's buffered decision edits to
 * `<opp>/inputs/decision-overrides.yaml`. The body carries no edits — the
 * server reads the shared Redis buffer as the authoritative set. No run
 * is created; the buffer clears on success.
 */
export async function saveDecisionOverrides(
  workspaceSlug: string,
  slug: string,
  sourceRunId: string,
): Promise<SaveDecisionOverridesResult> {
  const { data, response } = await apiClient.POST(
    "/api/w/{workspace_slug}/opps/{slug}/decision-overrides",
    {
      params: { path: { workspace_slug: workspaceSlug, slug } },
      body: { source_run_id: sourceRunId },
    },
  );
  if (!response.ok) throw new Error(`saveDecisionOverrides: ${response.status}`);
  return data as unknown as SaveDecisionOverridesResult;
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
  const { data, response } = await apiClient.GET("/api/w/{workspace_slug}/opps/{slug}/fork/status", {
    params: {
      path: { workspace_slug: workspaceSlug, slug },
      query: sourceRunId ? { source_run_id: sourceRunId } : {},
    },
  });
  if (!response.ok) throw new Error(`getForkStatus: ${response.status}`);
  return data as unknown as ForkProgress;
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
  artifactId: string,
): string {
  // Raw artifact content comes from the ninja backend's canonical
  // id-keyed endpoint: GET /artifacts/{artifact_id}/download (raw bytes).
  // The backend does NOT expose /steps/{skill}/artifacts/{name}, so the
  // old skill+name path 404'd for EVERY step's preview (the artifact pane
  // rendered "404"). Key by the artifact's Drive file id instead — it's
  // present on every step-detail artifact. BASE_URL keeps the raw fetch on
  // the /ace/ prefix nginx routes (a bare /api/... 404s in prod).
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  return (
    `${base}/api/w/${encodeURIComponent(workspaceSlug)}/opps/${encodeURIComponent(slug)}` +
    `/artifacts/${encodeURIComponent(artifactId)}/download` +
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
