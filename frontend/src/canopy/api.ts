import { apiClient } from "../api/apiClient";
import { getCanopyToken } from "./token";

/**
 * api.ts — browser → canopy-web REST.
 *
 * Two distinct call shapes live here:
 *
 *  - `createCanopySession` hits ace-web's OWN workspace-scoped
 *    `/api/w/{workspace_slug}/canopy/sessions` (session-authed, cookie +
 *    CSRF via `apiClient` — same as every other ace endpoint) because
 *    opp-linkage metadata (`opp_slug`/`opp_run_id`/`opp_step_skill`) AND the
 *    `origin_key` that scopes canopy's session list to THIS ace workspace
 *    are baked in server-side, from the membership-checked path parameter —
 *    never from anything the client sends. See apps/canopy/api.py.
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
  /**
   * Whether the session's bound runner is reachable right now (canopy's
   * `SessionOut.runner_online`) — `true`/`false` when there's a binding,
   * `null` when there is none (nothing to be offline). Canopy carries this
   * on the session itself rather than the caller having to cross-reference
   * the runner fleet, because `GET /api/harness/runners/` is scoped to
   * runners the caller personally PAIRED — a delegated ace user sees an
   * EMPTY fleet there and could never otherwise tell a stalled chat
   * ("bound runner offline, turn waiting") from a merely slow one
   * (fix-round-2 review, I5/offline-detection correction).
   */
  runner_online?: boolean | null;
}

/** `origin_key` this ace workspace stamps on (and filters by) every canopy
 *  session it creates/lists — must match `apps/canopy/api.py`'s server-side
 *  derivation (`f"ace-web:{workspace_slug}"`) exactly, since it's how canopy
 *  scopes the session LIST to one ace workspace instead of every ace
 *  workspace sharing the same canopy tenant (C1). */
export function aceOriginKey(workspaceSlug: string): string {
  return `ace-web:${workspaceSlug}`;
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
 * canopy_sessions.schemas.SessionOut has no `updated_at` field — it's
 * `last_activity_at` (mapped to our `updated_at`). `metadata` is NOT part of
 * SessionOut at all (it never was — an earlier draft of this mapping
 * optimistically passed it through; removed per M4 so it doesn't read as
 * available provenance when it can never actually be populated).
 */
function mapSessionSummary(raw: Record<string, unknown>): CanopySessionSummary {
  return {
    id: raw.id as string,
    title: raw.title as string,
    agent_slug: (raw.agent_slug as string | null | undefined) ?? null,
    updated_at: (raw.last_activity_at as string | undefined) ?? (raw.updated_at as string),
    runner_name: (raw.runner_name as string | null | undefined) ?? null,
    runner_online: (raw.runner_online as boolean | null | undefined) ?? null,
  };
}

export async function listCanopySessions(
  base: string,
  filters: { opp_slug?: string; opp_run_id?: string; state?: string; origin_key?: string } = {},
): Promise<CanopySessionSummary[]> {
  const params = new URLSearchParams({ source: "ace-web" });
  if (filters.opp_slug) params.set("opp_slug", filters.opp_slug);
  if (filters.opp_run_id) params.set("opp_run_id", filters.opp_run_id);
  if (filters.state) params.set("state", filters.state);
  // Scopes the list to THIS ace workspace (C1) — canopy filters on the
  // opaque metadata.origin_key it never otherwise interprets. Omitted (no
  // filter applied) only when the caller has no ace workspace to scope by.
  if (filters.origin_key) params.set("origin_key", filters.origin_key);

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

export async function createCanopySession(
  workspaceSlug: string,
  input: {
    title?: string;
    opp_slug?: string;
    opp_run_id?: string;
    opp_step_skill?: string;
  } = {},
): Promise<{ id: string }> {
  const { data, response } = await apiClient.POST("/api/w/{workspace_slug}/canopy/sessions", {
    params: { path: { workspace_slug: workspaceSlug } },
    body: {
      title: input.title ?? "",
      opp_slug: input.opp_slug ?? "",
      opp_run_id: input.opp_run_id ?? "",
      opp_step_skill: input.opp_step_skill ?? "",
    },
  });
  if (!response.ok) {
    throw new Error(`Failed to create canopy session: ${response.status}`);
  }
  return data as unknown as { id: string };
}

/** One backward page of transcript ("Load earlier"). Threads canopy's own
 *  `has_more_before` through (Ledger minor) rather than discarding it — the
 *  caller previously had to infer "any more before this?" from `messages.length
 *  === 0`, which is wrong the moment the page size ever changes from 1:1
 *  with "no more history". */
export async function fetchOlderMessages(
  base: string,
  id: string,
  before: number,
): Promise<{ messages: unknown[]; has_more_before: boolean }> {
  return canopyJson<{ messages: unknown[]; has_more_before: boolean }>(
    base,
    `/api/canopy-sessions/${encodeURIComponent(id)}/messages?before=${encodeURIComponent(String(before))}`,
  );
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

/**
 * `GET /api/harness/runners/` is scoped to runners the CALLER personally
 * paired (`apps/harness/api.py::_runner_visibility_q`) — a delegated ace
 * user typically has paired none, so this usually returns `[]`. It is only
 * useful here for the "continue on…" picker's list of alternatives, never
 * for detecting whether the session's OWN bound runner is offline (use
 * `CanopySessionDetail.runner_online` for that — fix-round-2 correction).
 */
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
