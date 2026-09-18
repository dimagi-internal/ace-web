import { CanopyRestError } from "canopy-client";

import { apiClient } from "../api/apiClient";
import type { components as canopy } from "../api/canopy-generated";
import { canopyRest } from "./client";

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

/**
 * canopy's own response shapes, generated from ITS OpenAPI schema
 * (`npm run gen:canopy-api`) rather than described again here.
 *
 * Every mapper below takes one of these instead of `Record<string, unknown>`,
 * which is the whole point: a field canopy renames or drops becomes a compile
 * error at the mapping site. It was a runtime surprise before — an earlier
 * draft compared `Runner.live_status` against `"ONLINE"`, the Python
 * constant's NAME rather than its lowercase VALUE, and every runner silently
 * looked offline.
 */
type SessionOut = canopy["schemas"]["SessionOut"];
type SessionDetailOut = canopy["schemas"]["SessionDetailOut"];
type RunnerOut = canopy["schemas"]["RunnerOut"];
type EmdashSessionOut = canopy["schemas"]["EmdashSessionOut"];
type TurnOut = canopy["schemas"]["TurnOut"];
type TurnEventsOut = canopy["schemas"]["TurnEventsOut"];
type MessagePageOut = canopy["schemas"]["MessagePageOut"];

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

/** Re-exported from `client.ts`, where it sits next to the rest config it
 *  belongs to. Kept here so existing importers do not have to move. */
export { aceOriginKey } from "./client";

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

/**
 * Bearer + retry-once-on-401, from `canopy-client`.
 *
 * This was ~30 hand-rolled lines here and is the machinery canopy-web extracted
 * into the package. The retry semantics are unchanged and deliberately so: on a
 * 401 the token is re-minted with `force`, because canopy has already rejected
 * it and our own expiry bookkeeping is not the authority (it may have been
 * revoked early, or the clocks may disagree).
 *
 * The ace-specific endpoints below ride on these rather than importing the
 * package's `listSessions`/`getSession`, because ace-web's shapes are snake_case
 * (`has_more_before`, `runner_online`) where the package normalises to camel,
 * and its session list also filters by `opp_slug`/`opp_run_id`, which the
 * package does not model. Sharing the TRANSPORT is the win; re-shaping ~20 call
 * sites to gain nothing is not.
 */
function canopyFetch(base: string, path: string, init: RequestInit = {}): Promise<Response> {
  return canopyRest(base).raw(path, init);
}

async function canopyJson<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  try {
    return await canopyRest(base).json<T>(path, init);
  } catch (err) {
    // The package throws a typed `CanopyRestError` carrying `status` and
    // `path`; ace-web's callers have always caught a plain `Error` and shown
    // its message, so preserve that surface rather than churn every catch.
    if (err instanceof CanopyRestError) {
      throw new Error(`canopy request failed (${err.status}): ${err.path}`);
    }
    throw err;
  }
}

/**
 * canopy_sessions.schemas.SessionOut has no `updated_at` field — it's
 * `last_activity_at` (mapped to our `updated_at`). `metadata` is NOT part of
 * SessionOut at all (it never was — an earlier draft of this mapping
 * optimistically passed it through; removed per M4 so it doesn't read as
 * available provenance when it can never actually be populated).
 */
function mapSessionSummary(raw: SessionOut): CanopySessionSummary {
  return {
    id: raw.id,
    title: raw.title,
    agent_slug: raw.agent_slug ?? null,
    updated_at: raw.last_activity_at,
    runner_name: raw.runner_name ?? null,
    runner_online: raw.runner_online ?? null,
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

  const rows = await canopyJson<SessionOut[]>(
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
  const raw = await canopyJson<SessionDetailOut>(
    base,
    `/api/canopy-sessions/${encodeURIComponent(id)}`,
  );
  return {
    ...mapSessionSummary(raw),
    has_more_before: raw.has_more_before,
    oldest_loaded_turn_index: raw.oldest_loaded_turn_index ?? null,
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
): Promise<MessagePageOut> {
  return canopyJson<MessagePageOut>(
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

/**
 * What the Workbench is currently showing, as state the agent can re-read
 * (canopy's `PUT /api/canopy-sessions/{id}/page-state`, spec
 * 2026-09-12-embedded-agent-widget-v2 §5).
 *
 * **Send the SELECTION, not the data.** `visible_ids` + `backing_tool` says
 * which rows are on screen and which MCP tool resolves them; the agent then
 * calls that tool itself, live, under the caller's own permissions. Serialising
 * the rows here would duplicate our own API, go stale between render and send,
 * and create a second place to get access control wrong — which is why canopy
 * caps a declaration at 8 KiB and refuses anything larger with `too_large`.
 * The cap is generous for hundreds of ids and deliberately too small for the
 * rows behind them.
 */
export interface CanopyPageState {
  /** An MCP resource URI naming WHAT is on screen, e.g. `opp://<slug>/<run>`. */
  resource: string;
  /** The MCP tool that resolves the rows this page is showing. */
  backing_tool?: string;
  /** Which rows, by identifier — never the rows themselves. */
  visible_ids?: (string | number)[];
  /** What the user narrowed to. */
  filters?: Record<string, unknown>;
  [key: string]: unknown;
}

/** Canopy refused the declaration itself (422) — the page must send something
 *  different, which is a different fix from retrying. `too_large` is the only
 *  code that fires in practice. */
export class CanopyPageStateRejected extends Error {
  readonly code: string;
  constructor(code: string, detail: string) {
    super(`canopy refused the page state (${code}): ${detail}`);
    this.code = code;
  }
}

/**
 * Replace this session's declared page state wholesale.
 *
 * Wholesale, never merged — a key left over from the step the user navigated
 * away from is a key the agent would reason about as though it were still on
 * screen, and merging makes stale state indistinguishable from fresh.
 */
export async function declareCanopyPageState(
  base: string,
  sessionId: string,
  state: CanopyPageState,
): Promise<void> {
  const response = await canopyFetch(
    base,
    `/api/canopy-sessions/${encodeURIComponent(sessionId)}/page-state`,
    { method: "PUT", body: JSON.stringify({ state }) },
  );
  if (response.status === 422) {
    // Ninja renders these as `{"detail": "<code>: <message>"}`. Surfacing the
    // code matters because `too_large` means "you sent rows instead of ids" —
    // a design mistake with a specific fix — and retrying it never helps.
    const detail = await response.text().catch(() => "");
    const code = /"detail"\s*:\s*"([a-z_]+):/.exec(detail)?.[1] ?? "rejected";
    throw new CanopyPageStateRejected(code, detail.slice(0, 200));
  }
  if (!response.ok) {
    throw new Error(`canopy request failed (${response.status}): page-state`);
  }
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
  const rows = await canopyJson<RunnerOut[]>(base, `/api/harness/runners/`);
  return rows.map((raw) => ({
    id: raw.id,
    name: raw.name,
    live_status: raw.status,
    ready: raw.ready,
    capabilities: raw.capabilities,
  }));
}

/** One live run a runner is executing right now, from canopy's harness feed. */
export interface ActiveRun {
  /** A canopy Session id — openable at /w/:ws/chat/c/:id, the same live,
   *  interactive view a chat uses. That is the whole reason this is useful:
   *  discovery is the missing half, the viewer already exists. */
  id: string;
  /** The runner's own name for the work — an emdash worktree/task slug. The
   *  only human-legible label a runner-discovered session has; these sessions
   *  carry no title, because nobody typed one. */
  task: string;
  project: string;
  /** The agent this run belongs to. Null on rows older than canopy-web #694,
   *  and on a genuine repo checkout that is nobody's agent. */
  agent: string | null;
  runner_name: string | null;
  status: string;
  last_interacted_at: string | null;
  /** Tail of what the run has said. Lets the list show what a run is DOING
   *  rather than just that it exists. */
  latest_message: string | null;
}

/**
 * `GET /api/harness/sessions` — open sessions on live runners, across the
 * caller's workspaces, newest first.
 *
 * Deliberately NOT `listCanopySessions`: that one filters to
 * `source=ace-web` + this workspace's `origin_key`, so it shows only sessions
 * ace-web itself created. A run started any other way — an inbound email
 * ringing the runner, a local emdash session, a scheduled turn — never appears
 * there. Those are exactly the runs someone wants to watch, so they need the
 * harness feed instead.
 *
 * User-scoped rather than workspace-scoped on the server (`list_visible_
 * sessions(request.user)`), so no workspace argument is threaded here.
 */
export async function listActiveRuns(base: string): Promise<ActiveRun[]> {
  const rows = await canopyJson<EmdashSessionOut[]>(base, `/api/harness/sessions`);
  return rows.map((raw) => {
    // `recent_messages` is `readonly unknown[]` in canopy's OWN schema — it
    // declares the field but not the element shape, so `.text` is the one thing
    // on this path the generated contract cannot check for us. Narrowed here,
    // in one place and out loud, rather than cast invisibly inside the map:
    // if canopy ever renames it, this is where to look, and nothing above
    // silently starts rendering blanks.
    const messages = (raw.recent_messages ?? []) as readonly { text?: string }[];
    // The LAST message is the newest — the feed returns them in order, and the
    // point of showing one is "what is it doing now".
    const last = messages.length ? messages[messages.length - 1]?.text : undefined;
    return {
      id: raw.id,
      task: raw.emdash_task ?? "",
      project: raw.project ?? "",
      agent: raw.agent ?? null,
      runner_name: raw.runner_name ?? null,
      status: raw.status ?? "",
      last_interacted_at: raw.last_interacted_at ?? null,
      latest_message: last ?? null,
    };
  });
}

/**
 * An in-flight TURN — a discrete unit of work a runner claimed.
 *
 * The other half of "what is ACE doing right now", and the half the sessions
 * feed structurally cannot show. `GET /api/harness/sessions` is derived from
 * emdash's sqlite, so it only ever contains runs on a box that HAS emdash — the
 * laptops. The cloud runner has none (it spawns `claude -p` headless), reports
 * `sessions=[]` on every heartbeat, and is therefore invisible there.
 *
 * It is not invisible in general: `cloud_runner.py` emits `status` / `assistant`
 * / `tool_start` / `tool_end` for EVERY turn it runs. An inbound-email turn
 * measured on 2026-09-08 carried 184 of them. Turns are where a cloud run lives.
 */
export interface ActiveTurn {
  id: string;
  agent: string | null;
  project: string;
  origin: string;
  status: string;
  prompt: string;
  runner_name: string | null;
  created_at: string;
  /** The canopy Session this turn drives, when it drives one. Empty for an
   *  email / scheduled / api turn — which is exactly the case with no session
   *  row to dedupe against. */
  session_id: string;
}

/**
 * `GET /api/harness/turns/` — recent turns for one agent, newest first.
 *
 * Deliberately unfiltered by status on the wire: the endpoint takes a `status`
 * query, but asking for "running" alone hides a turn that is still `queued`
 * behind a strict routing rule — which reads as "nothing is happening" at the
 * exact moment someone is waiting for their email to be picked up.
 */
export async function listActiveTurns(base: string, agent = "ace"): Promise<ActiveTurn[]> {
  const rows = await canopyJson<TurnOut[]>(
    base, `/api/harness/turns/?agent=${encodeURIComponent(agent)}&limit=25`,
  );
  return rows.map((raw) => ({
    id: raw.id,
    agent: raw.agent_slug ?? null,
    project: raw.project ?? "",
    origin: raw.origin ?? "",
    status: raw.status ?? "",
    prompt: raw.prompt ?? "",
    runner_name: raw.claimed_by_name ?? null,
    created_at: raw.created_at ?? "",
    session_id: raw.session_id ?? "",
  }));
}

/** Turns still in flight, and not already shown as a session.
 *
 *  A chat turn on a laptop drives a Session that the sessions feed ALSO lists;
 *  showing both would double every laptop run. A turn whose `session_id` names
 *  a listed session is therefore dropped — the session row is the better
 *  surface for it, because it opens into the full chat view.
 *
 *  `keepIds` pins turns that must survive the status filter regardless of how
 *  they ended (ace-web#757). The caller passes the turn the reader currently has
 *  OPEN: `ActiveRuns` renders `TurnWatch` *inside* the row, and this list is
 *  replaced wholesale every 15s, so without the pin a turn that finishes while
 *  someone is reading it takes the output off their screen mid-sentence — and
 *  nothing else in ace-web links to a finished turn, so it cannot be reopened.
 *  Pinning only what is open is deliberate: closing it drops the row on the next
 *  tick, which is the reader's own choice rather than a poll's. The session-dedupe
 *  above still wins over a pin — a turn whose session is listed belongs on the
 *  session row, which does not vanish. */
export function liveTurns(
  turns: ActiveTurn[],
  sessionIds: readonly string[] = [],
  keepIds: readonly string[] = [],
): ActiveTurn[] {
  const seen = new Set(sessionIds);
  const keep = new Set(keepIds);
  return turns.filter(
    (t) =>
      (t.status === "running" || t.status === "queued" || keep.has(t.id)) &&
      !seen.has(t.session_id),
  );
}

/** One streamed event from a turn. */
export interface TurnEvent {
  seq: number;
  ts: string;
  kind: string;
  payload: Record<string, unknown>;
}

/**
 * `GET /api/harness/turns/{id}/events?after=<seq>` — the append-only ledger.
 *
 * Incremental by sequence number: the server caps a response at 500 rows, so a
 * long run must be paged with `after` rather than re-fetched, and polling with
 * the last seq is what makes this a live view instead of a repeated download.
 */
export async function listTurnEvents(
  base: string, turnId: string, after = 0,
): Promise<TurnEvent[]> {
  const body = await canopyJson<TurnEventsOut>(
    base, `/api/harness/turns/${encodeURIComponent(turnId)}/events?after=${after}`,
  );
  // Structurally identical to canopy's `TurnEventOut`; the local `TurnEvent`
  // stays as the name this app's components import.
  return (body.events ?? []) as TurnEvent[];
}

/** The runs worth showing on an ACE surface: this agent's, still going.
 *
 *  Prefers the feed's `agent`, which canopy-web #694 made real — a reported
 *  session is now attributed to the agent whose project names it, rather than
 *  left null and filed under whichever machine happened to run it.
 *
 *  `project` stays as a fallback for rows written BEFORE that fix which the
 *  backfill could not claim (a project matching no agent slug), and for a
 *  deployment still running older canopy. Both are the same signal — `project`
 *  IS the agent's repo by convention — so the fallback narrows over time
 *  rather than competing. */
export function aceRuns(runs: ActiveRun[], slug = "ace"): ActiveRun[] {
  return runs.filter(
    (r) => r.status === "in_progress" && (r.agent === slug || (!r.agent && r.project === slug)),
  );
}
