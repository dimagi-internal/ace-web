import { useCallback, useEffect, useMemo, useState } from "react";

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
 *  the "Continue on…" picker. */
function onlineSessionCapableRunners(fleet: readonly CanopyRunnerSummary[]): CanopyRunnerSummary[] {
  return fleet.filter((r) => r.live_status === RUNNER_STATUS_ONLINE && isSessionCapable(r));
}

/** Whether the session's bound runner (matched by name — canopy's
 *  `SessionOut` carries no runner id, only `runner_name`) is offline. A
 *  name with no fleet match is NOT treated as offline — that's an unknown,
 *  not evidence, so the banner fails quiet rather than alarms on stale or
 *  not-yet-loaded fleet data. */
function isBoundRunnerOffline(
  runnerName: string | null | undefined,
  fleet: readonly Pick<CanopyRunnerSummary, "name" | "live_status">[],
): boolean {
  if (!runnerName) return false;
  const match = fleet.find((r) => r.name === runnerName);
  if (!match) return false;
  return match.live_status !== RUNNER_STATUS_ONLINE;
}

const FLEET_POLL_MS = 30_000;

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

  const wsUrl = useCallback(
    (_path: string) => {
      // The kit calls this builder on every (re)connect. Kick off a token
      // refresh check (fire-and-forget) each time so a soon-to-expire
      // token is refreshed in the background before the NEXT reconnect
      // attempt, even if this attempt's URL was built from the old one —
      // buildCanopyWsUrl reads the token synchronously via
      // peekCanopyToken().
      void getCanopyToken();
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
  const [runnerName, setRunnerName] = useState<string | null>(null);
  const [fleetRunners, setFleetRunners] = useState<CanopyRunnerSummary[]>([]);
  const [placing, setPlacing] = useState(false);
  const [placeInfo, setPlaceInfo] = useState<string | null>(null);
  const [placeError, setPlaceError] = useState<string | null>(null);

  // --- "Load earlier" history ----------------------------------------------
  const [hasMoreBefore, setHasMoreBefore] = useState(false);
  const [loadingEarlier, setLoadingEarlier] = useState(false);

  // The single-session detail (NOT the filtered/paginated list — Important
  // 2) for `runner_name` (the socket's `session.state` snapshot carries no
  // liveness fields) and the real `has_more_before` (Important 3 — this
  // used to be hardcoded `true`, which is a lie for a session that's
  // already fully loaded). A later runner reassignment is picked up by the
  // recovery poll below re-deriving `boundOffline` against a refreshed
  // fleet, same as canopy-web's own page.
  useEffect(() => {
    let live = true;
    getCanopySession(base, sessionId)
      .then((detail) => {
        if (!live) return;
        setRunnerName(detail.runner_name ?? null);
        setHasMoreBefore(detail.has_more_before);
      })
      .catch(() => {
        /* non-fatal: the offline banner just won't have evidence to show,
           and "Load earlier" stays hidden until a later fetch succeeds */
      });
    return () => {
      live = false;
    };
  }, [base, sessionId]);

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

  const boundOffline = isBoundRunnerOffline(runnerName, fleetRunners);

  // Recovery poll while the banner is showing — a bound runner that comes
  // back later in the same page-load would otherwise leave a stale-offline
  // false positive forever (the fleet is otherwise only fetched once).
  useEffect(() => {
    if (!boundOffline) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      listCanopyRunners(base)
        .then((r) => {
          if (!cancelled) setFleetRunners(r);
        })
        .catch(() => {
          /* non-fatal: retry next tick */
        })
        .finally(() => {
          if (!cancelled) timer = setTimeout(tick, FLEET_POLL_MS);
        });
    };
    timer = setTimeout(tick, FLEET_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [boundOffline, base]);

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
        refreshFleet();
      })
      .catch(placementFail)
      .finally(() => setPlacing(false));
  }, [base, sessionId, placementFail, refreshFleet]);

  const continueOn = useCallback(
    (runnerId: string) => {
      if (!runnerId) return;
      setPlacing(true);
      setPlaceInfo(null);
      setPlaceError(null);
      placeCanopySession(base, sessionId, { runner_id: runnerId })
        .then(() => {
          setPlaceInfo("Placed — the new runner will pick it up shortly.");
          refreshFleet();
        })
        .catch(placementFail)
        .finally(() => setPlacing(false));
    },
    [base, sessionId, placementFail, refreshFleet],
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
      const older = await fetchOlderMessages(base, sessionId, oldestTurn);
      if (older.length === 0) {
        setHasMoreBefore(false);
        return;
      }
      socket.prependMessages(older.map(restToKitMessage));
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
      banner={
        boundOffline ? (
          <PlacementBanner
            runnerName={runnerName ?? ""}
            eligibleRunners={placementRunners}
            busy={placing}
            error={placeError}
            info={placeInfo}
            onWait={waitForIt}
            onPlace={continueOn}
          />
        ) : undefined
      }
    />
  );
}

export default CanopyChatPanel;
