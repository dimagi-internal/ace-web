import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ChatPanel,
  PlacementBanner,
  useSessionSocket,
  type Message,
  type PlacementRunner,
} from "canopy-ui/chat";

import { MarkdownRenderer } from "../components/MarkdownRenderer";
import { notifySessionsUpdated } from "../hooks/useRecentSessions";
import {
  RUNNER_STATUS_ONLINE,
  attachCanopySession,
  detachCanopySession,
  fetchOlderMessages,
  getCanopySession,
  listCanopyRunners,
  placeCanopySession,
  type CanopyRunnerSummary,
} from "./api";
import { getCanopyToken } from "./token";
import { useCanopyStatus } from "./useCanopyStatus";
import { buildCanopyWsUrl } from "./ws";

/** Render assistant/system message text through ace's existing shared
 *  markdown renderer (remark-gfm + rehype-highlight) — the same one every
 *  other AI-output surface in ace-web uses. Injected into the kit via its
 *  `renderMarkdown` seam so the kit itself stays free of react-markdown. */
function renderMarkdown(text: string) {
  return <MarkdownRenderer content={text} variant="chat" />;
}

/**
 * A REST `MessageOut` row (`turn_index`/`role`/`plaintext`/`content`/
 * `created_at` — canopy's `apps/canopy_sessions/schemas.py::MessageOut`) ->
 * the kit's `Message` shape. Synthetic id (`t<turn_index>`) + `status:
 * "complete"` — `prependMessages`'s dedupe (the kit's `prependHistory`)
 * keys on `turn_index`, so a synthetic-id row never collides with a live
 * WS row of the same index. Mirrors canopy-web's own
 * `pages/chatPageLogic.ts::restToKitMessage`.
 */
export function restToKitMessage(raw: unknown): Message {
  const m = raw as {
    turn_index: number;
    role: string;
    content: Record<string, unknown>;
    plaintext: string;
    created_at: string;
  };
  return {
    id: `t${m.turn_index}`,
    turn_index: m.turn_index,
    role: m.role as Message["role"],
    content: m.content,
    plaintext: m.plaintext,
    status: "complete",
    error_detail: null,
    started_at: null,
    completed_at: m.created_at,
    created_at: m.created_at,
  };
}

/** Only a session-CAPABLE runner (capabilities.sessions === true) can
 *  execute a chat turn. Mirrors canopy-web's
 *  `components/chat/runnerEligibility.ts::isSessionCapable`, adapted to
 *  `CanopyRunnerSummary`'s field names. */
function isSessionCapable(runner: Pick<CanopyRunnerSummary, "capabilities">): boolean {
  return runner.capabilities?.sessions === true;
}

/** Online + session-capable runners from the fleet — the eligible set for
 *  the "Continue on…" picker. Note: `GET /api/harness/runners/` is scoped to
 *  runners the CALLER personally paired, so for a delegated ace user this is
 *  typically empty — see the caller's handling of an empty result. */
function onlineSessionCapableRunners(fleet: readonly CanopyRunnerSummary[]): CanopyRunnerSummary[] {
  return fleet.filter((r) => r.live_status === RUNNER_STATUS_ONLINE && isSessionCapable(r));
}

// How often to re-poll the session detail while its bound runner is offline,
// so the banner clears itself the moment the runner comes back (fix-round-2:
// this used to poll the RUNNERS list, which a delegated user can't see —
// see the `runner_online`-based detection below).
const OFFLINE_RECOVERY_POLL_MS = 30_000;

// I5 round 2: minimum spacing between FORCED token refreshes issued from
// the WS reconnect path (see the `wsUrl` builder below) — a flapping
// socket riding the kit's reconnect ladder down to its 1s floor would
// otherwise force a fresh mint roughly once a second per open tab, and
// canopy's token-exchange endpoint has no rate limit (each call writes a
// new DelegatedToken row). Reconnects inside this window fall back to a
// normal cache-respecting (non-forced) read instead of being skipped
// outright, so a still-valid cached token keeps being used.
const FORCE_REFRESH_MIN_INTERVAL_MS = 30_000;

interface Props {
  sessionId: string;
  /** Optional extra side-effect on `session.title_updated`, beyond the
   *  default `notifySessionsUpdated()` broadcast every consumer already
   *  gets (so a sidebar/list showing this session's title re-fetches). */
  onTitleUpdated?: () => void;
}

/**
 * The ace-web twin of canopy-web's own `pages/ChatPage.tsx` container:
 * wires canopy's WebSocket URL + REST session/runner lookups + ace's
 * markdown renderer into the reusable `canopy-ui/chat` `ChatPanel`. A
 * drop-in chat body — `<CanopyChatPanel sessionId={id} />` — for any ace
 * surface (the dedicated `/w/:workspace/chat/c/:canopyId` route, or
 * embedded inline in the Workbench's chat pane).
 *
 * Doesn't mount the actual socket (`CanopyChatPanelBody`) until BOTH
 * `useCanopyStatus()` has resolved (so the WS URL is built from a real
 * `base_url`, not `""`) AND a token has been minted — the kit's
 * `useSessionSocket` connects immediately on mount, so mounting it before
 * either is ready opens a bogus/tokenless socket while the real one is
 * still loading (fix-round-1 review, Important 4). A brief "Connecting…"
 * shell renders instead.
 */
export function CanopyChatPanel({ sessionId, onTitleUpdated }: Props) {
  const status = useCanopyStatus();
  const [tokenReady, setTokenReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setTokenReady(false);
    getCanopyToken()
      .catch(() => {
        /* A failed mint shouldn't wedge the UI behind "Connecting…"
           forever — fall through and let the kit's own reconnect ladder
           handle it (peekCanopyToken() stays null, the WS omits ?token=,
           the server 4001s, the kit retries). */
      })
      .finally(() => {
        if (!cancelled) setTokenReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  if (!status || !tokenReady) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-sm text-muted-foreground">
        Connecting…
      </div>
    );
  }

  return <CanopyChatPanelBody sessionId={sessionId} base={status.base_url} onTitleUpdated={onTitleUpdated} />;
}

interface BodyProps {
  sessionId: string;
  base: string;
  onTitleUpdated?: () => void;
}

function CanopyChatPanelBody({ sessionId, base, onTitleUpdated }: BodyProps) {
  const handleTitleUpdated = useCallback(() => {
    // Broadcast on the same event bus RecentSessionsSidebar/legacy chat
    // lists already listen on, so any list rendering this session's title
    // re-fetches without a bespoke canopy-only channel.
    notifySessionsUpdated();
    onTitleUpdated?.();
  }, [onTitleUpdated]);

  // I5: the kit calls `wsUrl` on every (re)connect attempt. The very first
  // call is the initial connect; every call after that means the previous
  // attempt didn't stay connected — i.e. this IS a reconnect. A token that
  // was revoked (credential rotated, user deactivated) but isn't yet near
  // its cached TTL would otherwise be reused forever by a bare
  // `getCanopyToken()`, wedging the socket in a permanent 4001-reconnect
  // loop that only a page reload recovers from. Forcing a refresh on every
  // reconnect attempt (not just the first) fixes that without needing to
  // distinguish "revoked" from "network blip" — a forced mint is cheap and
  // idempotent-safe either way.
  //
  // Round-2 review fixes:
  //  1. `getCanopyToken` now actually issues a request on every reconnect
  //     (round 1 only read the cache), so a failing mint (canopy down,
  //     credential revoked) is now a real rejected promise on every
  //     attempt — `.catch()` it, or a canopy outage spews unhandled
  //     rejections into the console/error tracker on every reconnect tick.
  //  2. The kit's reconnect ladder bottoms out at a 1s delay
  //     (`RECONNECT_DELAYS_MS`) and resets its own attempt counter on every
  //     successful `onopen` — so a FLAPPING socket would otherwise force a
  //     fresh mint roughly once a second per open tab, and canopy's
  //     token-exchange endpoint has no rate limit of its own (each call
  //     writes a new `DelegatedToken` row). `lastForcedAtRef` caps forced
  //     refreshes to at most one per `FORCE_REFRESH_MIN_INTERVAL_MS`;
  //     within that window a reconnect falls back to a normal
  //     cache-respecting (non-forced) read, never storming the endpoint.
  //     Scoped to THIS panel's reconnect path only (not a global change to
  //     `getCanopyToken`'s contract) so the unrelated 401-retry-once path
  //     in api.ts keeps forcing unconditionally, as before.
  //  3. The reset-on-session-switch step below used to be a `useEffect`,
  //     but the kit's OWN mount effect (registered inside
  //     `useSessionSocket`, called above) fires BEFORE an effect declared
  //     later in this component's body — so on mount, the real initial
  //     connect bumped the counter 0→1, and this effect then clobbered it
  //     straight back to 0, meaning the real first reconnect looked
  //     identical to the initial connect and forcing only actually began
  //     on the SECOND reconnect. Resetting synchronously during render
  //     (comparing against the previous sessionId) instead of in an effect
  //     avoids that ordering race outright — refs are safe to mutate
  //     during render, and this always completes before any effect for
  //     the same commit runs.
  const lastForcedAtRef = useRef(0);
  const connectAttemptRef = useRef(0);
  const lastSessionIdRef = useRef(sessionId);
  if (lastSessionIdRef.current !== sessionId) {
    lastSessionIdRef.current = sessionId;
    connectAttemptRef.current = 0;
  }
  const wsUrl = useCallback(
    (_path: string) => {
      const isReconnect = connectAttemptRef.current > 0;
      connectAttemptRef.current += 1;
      const now = Date.now();
      const shouldForce =
        isReconnect && now - lastForcedAtRef.current >= FORCE_REFRESH_MIN_INTERVAL_MS;
      if (shouldForce) lastForcedAtRef.current = now;
      void getCanopyToken(shouldForce).catch(() => {
        /* non-fatal here: a failed mint just means this attempt's URL
           carries a stale/no token; the kit's own reconnect ladder (and
           the next tick's forced-or-not retry above) is what recovers,
           not this call succeeding. */
      });
      return buildCanopyWsUrl(base, sessionId);
    },
    [base, sessionId],
  );

  const socket = useSessionSocket({ sessionId, wsUrl, onTitleUpdated: handleTitleUpdated });

  // Viewer-liveness pair: tells the bound runner to start/stop streaming
  // this session live (RunnerBinding.stream_desired). Fire-and-forget on
  // mount/unmount — never block rendering on either call (fix-round-1
  // review, Scope gap 7). Chained off the attach promise (not raced)
  // so a StrictMode mount/unmount/remount double-invoke — or a plain fast
  // unmount — can't detach before its paired attach lands.
  useEffect(() => {
    const attached = attachCanopySession(base, sessionId).catch(() => {
      /* non-fatal: a failed attach just means no bound runner to notify */
    });
    return () => {
      void attached.finally(() => {
        void detachCanopySession(base, sessionId).catch(() => {
          /* non-fatal */
        });
      });
    };
  }, [base, sessionId]);

  // --- Placement banner: the session's bound runner going offline. --------
  //
  // Detected from the session detail's `runner_online` (fix-round-2
  // correction) — NOT by cross-referencing the runner fleet list, which is
  // scoped to runners the CALLER personally paired
  // (`apps/harness/api.py::_runner_visibility_q`). A delegated ace user has
  // typically paired none, so the fleet list is empty for them and matching
  // `runner_name` against it could never detect an offline bound runner.
  const [runnerName, setRunnerName] = useState<string | null>(null);
  const [runnerOnline, setRunnerOnline] = useState<boolean | null>(null);
  const [fleetRunners, setFleetRunners] = useState<CanopyRunnerSummary[]>([]);
  const [placing, setPlacing] = useState(false);
  const [placeInfo, setPlaceInfo] = useState<string | null>(null);
  const [placeError, setPlaceError] = useState<string | null>(null);

  // --- "Load earlier" history ----------------------------------------------
  const [hasMoreBefore, setHasMoreBefore] = useState(false);
  const [loadingEarlier, setLoadingEarlier] = useState(false);

  // The single-session detail (NOT the filtered/paginated list — Important
  // 2) for `runner_name`/`runner_online` (the socket's `session.state`
  // snapshot carries no liveness fields) and the real `has_more_before`
  // (Important 3 — this used to be hardcoded `true`, which is a lie for a
  // session that's already fully loaded).
  const refreshSessionDetail = useCallback(() => {
    return getCanopySession(base, sessionId)
      .then((detail) => {
        setRunnerName(detail.runner_name ?? null);
        setRunnerOnline(detail.runner_online ?? null);
        setHasMoreBefore(detail.has_more_before);
        return detail;
      })
      .catch(() => {
        /* non-fatal: the offline banner just won't have evidence to show,
           and "Load earlier" stays hidden until a later fetch succeeds */
        return null;
      });
  }, [base, sessionId]);

  useEffect(() => {
    void refreshSessionDetail();
  }, [refreshSessionDetail]);

  // The "continue on…" picker's alternatives — best-effort, usually empty
  // for a delegated user (see the function's own doc comment). Fetched
  // once; not part of offline detection.
  const refreshFleet = useCallback(() => {
    listCanopyRunners(base)
      .then((r) => setFleetRunners(r))
      .catch(() => {
        /* non-fatal: keep the last-known fleet snapshot */
      });
  }, [base]);

  useEffect(() => {
    refreshFleet();
  }, [refreshFleet]);

  // Reset all per-session UI state on a session switch. In every current
  // caller `CanopyChatPanel` is rendered with `key={sessionId}` (a fresh
  // mount per session), but resetting explicitly keeps this component
  // correct even if a future caller omits the key.
  useEffect(() => {
    setPlacing(false);
    setPlaceInfo(null);
    setPlaceError(null);
    setHasMoreBefore(false);
    setLoadingEarlier(false);
  }, [sessionId]);

  const boundOffline = runnerOnline === false;

  // Recovery poll while the banner is showing — re-polls the SESSION DETAIL
  // (not the runner fleet — fix-round-2) so a bound runner that comes back
  // later in the same page-load clears the banner, and so a delegated
  // user (who can't see the fleet at all) still gets the recovery signal.
  useEffect(() => {
    if (!boundOffline) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      refreshSessionDetail().finally(() => {
        if (!cancelled) timer = setTimeout(tick, OFFLINE_RECOVERY_POLL_MS);
      });
    };
    timer = setTimeout(tick, OFFLINE_RECOVERY_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [boundOffline, refreshSessionDetail]);

  const placementRunners: PlacementRunner[] = useMemo(
    () =>
      onlineSessionCapableRunners(fleetRunners).map((r) => ({
        id: r.id,
        name: r.name,
        online: r.live_status === RUNNER_STATUS_ONLINE,
      })),
    [fleetRunners],
  );

  const placementFail = useCallback((err: unknown) => {
    setPlaceError(err instanceof Error ? err.message : "Could not place the turn.");
  }, []);

  const waitForIt = useCallback(() => {
    setPlacing(true);
    setPlaceInfo(null);
    setPlaceError(null);
    placeCanopySession(base, sessionId, "wait")
      .then(() => {
        setPlaceInfo("Waiting for the bound runner.");
        refreshSessionDetail();
      })
      .catch(placementFail)
      .finally(() => setPlacing(false));
  }, [base, sessionId, placementFail, refreshSessionDetail]);

  const continueOn = useCallback(
    (runnerId: string) => {
      if (!runnerId) return;
      setPlacing(true);
      setPlaceInfo(null);
      setPlaceError(null);
      placeCanopySession(base, sessionId, { runner_id: runnerId })
        .then(() => {
          setPlaceInfo("Placed — the new runner will pick it up shortly.");
          refreshSessionDetail();
        })
        .catch(placementFail)
        .finally(() => setPlacing(false));
    },
    [base, sessionId, placementFail, refreshSessionDetail],
  );

  const oldestTurn = useMemo(() => {
    const messages = socket.state.messages;
    if (messages.length === 0) return null;
    return messages.reduce((min, m) => Math.min(min, m.turn_index), messages[0].turn_index);
  }, [socket.state.messages]);

  const loadEarlier = useCallback(async () => {
    if (oldestTurn == null || loadingEarlier) return;
    setLoadingEarlier(true);
    try {
      const page = await fetchOlderMessages(base, sessionId, oldestTurn);
      // Thread canopy's own has_more_before through (Ledger minor) instead
      // of inferring it from `messages.length === 0` — those aren't the
      // same thing the moment a page can be non-empty AND still be the
      // last one.
      setHasMoreBefore(page.has_more_before);
      if (page.messages.length > 0) {
        socket.prependMessages(page.messages.map(restToKitMessage));
      }
    } catch {
      /* keep what's shown; the button stays available to retry */
    } finally {
      setLoadingEarlier(false);
    }
  }, [base, sessionId, oldestTurn, loadingEarlier, socket]);

  const emptyState = useMemo(
    () => (
      <div className="flex h-full flex-col items-center justify-center gap-1 p-8 text-center text-sm text-muted-foreground">
        <div className="text-foreground">Start the conversation</div>
        <div className="text-xs">Type a message below to begin.</div>
      </div>
    ),
    [],
  );

  const showHistorySlot = hasMoreBefore && socket.state.messages.length > 0;
  const historySlot = !showHistorySlot ? undefined : (
    <div className="flex flex-col items-center gap-1 border-b border-border py-2">
      <button
        type="button"
        onClick={() => void loadEarlier()}
        disabled={loadingEarlier}
        className="rounded-md border border-border bg-card px-3 py-1 text-[12px] text-foreground-secondary hover:bg-muted disabled:opacity-50"
      >
        {loadingEarlier ? "Loading…" : "Load earlier"}
      </button>
    </div>
  );

  // The kit's PlacementBanner always renders a "Continue on…" picker,
  // regardless of how many `eligibleRunners` it's given. For a delegated
  // ace user `placementRunners` is typically empty (the fleet endpoint is
  // scoped to runners the caller personally paired), so showing that full
  // banner would present an empty dropdown with no real exit. Degrade to a
  // plain "wait for it" banner in that case instead.
  const banner = !boundOffline ? undefined : placementRunners.length > 0 ? (
    <PlacementBanner
      runnerName={runnerName ?? ""}
      eligibleRunners={placementRunners}
      busy={placing}
      error={placeError}
      info={placeInfo}
      onWait={waitForIt}
      onPlace={continueOn}
    />
  ) : (
    <div className="flex flex-wrap items-center gap-2 border-b border-warning/30 bg-warning/10 px-4 py-2 text-[12px] text-warning">
      <span className="font-medium">{(runnerName || "The bound runner") + " is unavailable"}</span>
      <button
        type="button"
        onClick={waitForIt}
        disabled={placing}
        className="rounded-md border border-warning/40 px-2 py-0.5 text-warning hover:bg-warning/20 disabled:opacity-50"
      >
        Wait for it
      </button>
      {placeError && <span className="text-destructive">{placeError}</span>}
      {placeInfo && <span className="text-muted-foreground">{placeInfo}</span>}
    </div>
  );

  return (
    <ChatPanel
      state={socket.state}
      connected={socket.connected}
      currentUserId={socket.state.current_user_id}
      onSend={socket.sendChat}
      onStop={socket.stopChat}
      onUpdateDraft={socket.updateDraft}
      onTakeOver={socket.takeOverDraft}
      onDiscard={socket.discardDraft}
      renderMarkdown={renderMarkdown}
      emptyState={emptyState}
      historySlot={historySlot}
      // Belt-and-suspenders alongside the outer "Connecting…" gate: even
      // once mounted, disable sending while the socket isn't actually
      // OPEN (initial connect settling, or any later drop/reconnect) so a
      // message typed in that window can't be lost to a socket that's
      // about to be replaced.
      disabledReason={socket.connected ? undefined : "Reconnecting…"}
      banner={banner}
    />
  );
}

export default CanopyChatPanel;
