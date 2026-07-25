import { apiClient } from "../api/apiClient";
import { getCanopyToken } from "./token";

/**
 * api.ts — browser → canopy-web REST.
 *
 * Two distinct call shapes live here:
 *
 *  - `createCanopySession` hits ace-web's OWN `/api/canopy/sessions`
 *    (session-authed, cookie + CSRF via `apiClient` — same as every other
 *    ace endpoint) because opp-linkage metadata (`opp_slug`/`opp_run_id`/
 *    `opp_step_skill`) is baked in server-side. See apps/canopy/api.py.
 *  - Everything else talks to canopy-web directly at `${base}` (canopy's
 *    `CanopyStatus.base_url`) with `Authorization: Bearer <delegated
 *    token>` — canopy-web has no ace session cookie to check. A 401 gets
 *    exactly one retry with a forced token refresh (`getCanopyToken(true)`)
 *    before giving up, matching token.ts's cache-invalidation contract.
 *
 * Response field names are matched against canopy-web's actual schemas
 * (apps/canopy_sessions/schemas.py, apps/harness/schemas.py) rather than
 * guessed — see the per-function mapping notes below.
 */

export interface CanopySessionSummary {
  id: string;
  title: string;
  agent_slug: string | null;
  updated_at: string;
  runner_name?: string | null;
  metadata?: Record<string, string>;
}

/** `GET /api/canopy-sessions/{id}` (`SessionDetailOut`) — the single-session
 *  detail fetch. Unlike `listCanopySessions`, this is NOT filtered by
 *  `state=active` or capped by a page `limit`, so it's the correct source
 *  for "does THIS session have a bound runner" / "does THIS session have
 *  more history before the loaded window" — an archived or page-201st
 *  session silently vanishes from the list endpoint but is still directly
 *  gettable here (fix-round-1 review, Important 2). */
export interface CanopySessionDetail extends CanopySessionSummary {
  has_more_before: boolean;
  oldest_loaded_turn_index: number | null;
}

async function canopyFetch(base: string, path: string, init: RequestInit = {}): Promise<Response> {
  const doFetch = (bearer: string) =>
    fetch(`${base}${path}`, {
      ...init,
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
        Authorization: `Bearer ${bearer}`,
      },
    });

  const token = await getCanopyToken();
  let response = await doFetch(token);
  if (response.status === 401) {
    const fresh = await getCanopyToken(true);
    response = await doFetch(fresh);
  }
  return response;
}

async function canopyJson<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const response = await canopyFetch(base, path, init);
  if (!response.ok) {
    throw new Error(`canopy request failed (${response.status}): ${path}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/**
 * canopy_sessions.schemas.SessionOut has no `updated_at`/`metadata` fields —
 * it's `last_activity_at` (mapped to our `updated_at`) and no metadata at
 * all today. `metadata` is passed through opportunistically (undefined if
 * canopy never sends it) so this mapping doesn't need to change the moment
 * canopy-web starts returning it.
 */
function mapSessionSummary(raw: Record<string, unknown>): CanopySessionSummary {
  return {
    id: raw.id as string,
    title: raw.title as string,
    agent_slug: (raw.agent_slug as string | null | undefined) ?? null,
    updated_at: (raw.last_activity_at as string | undefined) ?? (raw.updated_at as string),
    runner_name: (raw.runner_name as string | null | undefined) ?? null,
    metadata: raw.metadata as Record<string, string> | undefined,
  };
}

export async function listCanopySessions(
  base: string,
  filters: { opp_slug?: string; opp_run_id?: string; state?: string } = {},
): Promise<CanopySessionSummary[]> {
  const params = new URLSearchParams({ source: "ace-web" });
  if (filters.opp_slug) params.set("opp_slug", filters.opp_slug);
  if (filters.opp_run_id) params.set("opp_run_id", filters.opp_run_id);
  if (filters.state) params.set("state", filters.state);

  const rows = await canopyJson<Record<string, unknown>[]>(
    base,
    `/api/canopy-sessions/?${params.toString()}`,
  );
  return rows.map(mapSessionSummary);
}

/**
 * `GET /api/canopy-sessions/{id}` — a single session's detail, including
 * `has_more_before`/`oldest_loaded_turn_index` (absent from the list
 * endpoint's `SessionOut` rows). This is the correct call for "does THIS
 * one session have a bound runner right now" — `listCanopySessions` and
 * filtering client-side silently misses an archived or page-201st session
 * (fix-round-1 review, Important 2).
 */
export async function getCanopySession(base: string, id: string): Promise<CanopySessionDetail> {
  const raw = await canopyJson<Record<string, unknown>>(
    base,
    `/api/canopy-sessions/${encodeURIComponent(id)}`,
  );
  return {
    ...mapSessionSummary(raw),
    has_more_before: Boolean(raw.has_more_before),
    oldest_loaded_turn_index:
      (raw.oldest_loaded_turn_index as number | null | undefined) ?? null,
  };
}

export async function createCanopySession(input: {
  title?: string;
  opp_slug?: string;
  opp_run_id?: string;
  opp_step_skill?: string;
}): Promise<{ id: string }> {
  // Not in generated.ts yet — see the note on token.ts's requestToken().
  const { response } = await apiClient.POST("/api/canopy/sessions" as never, {
    body: {
      title: input.title ?? "",
      opp_slug: input.opp_slug ?? "",
      opp_run_id: input.opp_run_id ?? "",
      opp_step_skill: input.opp_step_skill ?? "",
    },
  } as never);
  if (!response.ok) {
    throw new Error(`Failed to create canopy session: ${response.status}`);
  }
  return (await response.json()) as { id: string };
}

export async function fetchOlderMessages(base: string, id: string, before: number): Promise<unknown[]> {
  const page = await canopyJson<{ messages: unknown[]; has_more_before: boolean }>(
    base,
    `/api/canopy-sessions/${encodeURIComponent(id)}/messages?before=${encodeURIComponent(String(before))}`,
  );
  return page.messages;
}

// The REST twin of the kit's WS `chat.stop` (useSessionSocket's `stopChat`) —
// this endpoint stops the session's in-flight turn from outside an open
// socket (e.g. before one has been established).
export async function stopCanopySession(base: string, id: string): Promise<void> {
  await canopyJson<void>(base, `/api/canopy-sessions/${encodeURIComponent(id)}/stop`, { method: "POST" });
}

// The viewer-liveness pair (`RunnerBinding.stream_desired`): attaching tells
// the bound runner to start streaming this session live; detaching lets it
// stop once the last viewer leaves. Best-effort — callers (CanopyChatPanel)
// fire these on mount/unmount and never block rendering on the result.
export async function attachCanopySession(base: string, id: string): Promise<void> {
  await canopyFetch(base, `/api/canopy-sessions/${encodeURIComponent(id)}/attach`, {
    method: "POST",
  });
}

export async function detachCanopySession(base: string, id: string): Promise<void> {
  await canopyFetch(base, `/api/canopy-sessions/${encodeURIComponent(id)}/detach`, {
    method: "POST",
  });
}

export async function placeCanopySession(
  base: string,
  id: string,
  placement: "wait" | { runner_id: string },
): Promise<void> {
  // canopy_sessions.schemas.PlaceIn.placement is a plain string on the wire:
  // "wait", or a runner UUID string. The `{runner_id}` shape is purely our
  // TS ergonomics — flatten it before sending.
  const wirePlacement = placement === "wait" ? "wait" : placement.runner_id;
  await canopyJson<void>(base, `/api/canopy-sessions/${encodeURIComponent(id)}/place`, {
    method: "POST",
    body: JSON.stringify({ placement: wirePlacement }),
  });
}

/**
 * `Runner.live_status`'s wire VALUES (`apps/harness/models.py`:
 * `ONLINE, STALE, DISCONNECTED, DEGRADED, RETIRED = ("online", "stale",
 * "disconnected", "degraded", "retired")`) — lowercase, passed through
 * unchanged by `listCanopyRunners` below. Referenced as a shared constant
 * (rather than repeating the literal at every comparison site) after
 * fix-round-1's Critical 1: an earlier draft compared against `"ONLINE"`
 * (the Python CONSTANT's name, not its value), which made every runner
 * look offline and mis-fired the placement banner on every chat.
 */
export const RUNNER_STATUS_ONLINE = "online";

export interface CanopyRunnerSummary {
  id: string;
  name: string;
  live_status?: string;
  ready?: boolean;
  capabilities?: Record<string, unknown>;
}

export async function listCanopyRunners(base: string): Promise<CanopyRunnerSummary[]> {
  // harness.schemas.RunnerOut's wire field is `status` (resolved from the
  // model's `live_status` — values are lowercase: online/stale/disconnected/
  // degraded/retired, see RUNNER_STATUS_ONLINE above) — renamed here to
  // `live_status` to match what the directed-routing UI actually reasons
  // about, per the interface Task 4 consumes.
  const rows = await canopyJson<Record<string, unknown>[]>(base, `/api/harness/runners/`);
  return rows.map((raw) => ({
    id: raw.id as string,
    name: raw.name as string,
    live_status: raw.status as string | undefined,
    ready: raw.ready as boolean | undefined,
    capabilities: raw.capabilities as Record<string, unknown> | undefined,
  }));
}
