import { useCallback, useEffect, useRef, useState } from "react";

import type { SessionState, WsEvent } from "../api/types";
import { wsUrl } from "../lib/wsUrl";
import { sessionReducer } from "./sessionReducer";
import { notifySessionsUpdated } from "./useRecentSessions";

const HEARTBEAT_INTERVAL_MS = 20_000;
const RECONNECT_DELAYS_MS = [1_000, 2_000, 5_000, 10_000];
const DRAFT_UPDATE_DEBOUNCE_MS = 150;

const INITIAL_STATE: SessionState = {
  messages: [],
  active_draft: null,
  participants: [],
  presence_user_ids: [],
  current_user_id: 0,
};

function wsUrlFor(slug: string): string {
  return wsUrl(`ws/sessions/${slug}/`);
}

export interface UseSessionSocketResult {
  state: SessionState;
  connected: boolean;
  sendChat: () => void;
  stopChat: (messageId: number) => void;
  updateDraft: (body: string) => void;
  takeOverDraft: () => void;
  discardDraft: () => void;
  lastError: string | null;
}

export function useSessionSocket(slug: string): UseSessionSocketResult {
  const [state, setState] = useState<SessionState>(INITIAL_STATE);
  const [connected, setConnected] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const stateRef = useRef<SessionState>(INITIAL_STATE);
  const reconnectAttemptRef = useRef(0);
  const heartbeatTimerRef = useRef<number | null>(null);
  const draftDebounceRef = useRef<number | null>(null);
  const pendingDraftBodyRef = useRef<string | null>(null);
  const closedByUserRef = useRef(false);
  // Control frames that must not be lost across a reconnect (currently
  // only chat.stop). The WS-world analogue of open-agents'
  // AbortableChatTransport. See docs/learnings/stream-resume-vercel-open-agents.md.
  const pendingFramesRef = useRef<{ action: string; data: unknown }[]>([]);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const send = useCallback((frame: { action: string; data: unknown }) => {
    const ws = socketRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(frame));
      return;
    }
    // Queue chat.stop so a stop clicked while the socket is reconnecting
    // is delivered on next OPEN instead of silently dropped. Draft updates
    // are intentionally NOT queued — they have a version guard and the
    // user's next keystroke will refresh the body anyway.
    if (frame.action === "chat.stop") {
      pendingFramesRef.current.push(frame);
    }
  }, []);

  const applyEvent = useCallback((frame: WsEvent) => {
    // Side-effect events: handle BEFORE setState so React strict-mode's
    // double-invocation of the updater doesn't double-fire the effect.
    if (frame.event === "session.title_updated") {
      // Tells RecentSessionsSidebar AND ChatPage's header to re-fetch.
      // Both already listen for this event for user-driven changes
      // (rename); piggy-backing the auto-title broadcast onto the same
      // channel keeps them consistent.
      notifySessionsUpdated();
      return;
    }
    if (frame.event === "session.error") {
      setLastError(frame.data.message);
      if (
        frame.data.code === "draft_version_mismatch" &&
        frame.data.detail &&
        typeof frame.data.detail === "object"
      ) {
        // Clear any pending optimistic body so the user's stale local
        // text doesn't auto-re-send with the new version.
        pendingDraftBodyRef.current = null;
        if (draftDebounceRef.current != null) {
          window.clearTimeout(draftDebounceRef.current);
          draftDebounceRef.current = null;
        }
      }
    }
    setState((prev) => sessionReducer(prev, frame));
  }, []);

  const connect = useCallback(() => {
    if (closedByUserRef.current) return;
    const ws = new WebSocket(wsUrlFor(slug));
    socketRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      reconnectAttemptRef.current = 0;
      // Flush any control frames that were queued while the socket was
      // closed. See `send` above.
      const queued = pendingFramesRef.current;
      pendingFramesRef.current = [];
      for (const frame of queued) {
        ws.send(JSON.stringify(frame));
      }
      if (heartbeatTimerRef.current != null) {
        window.clearInterval(heartbeatTimerRef.current);
      }
      heartbeatTimerRef.current = window.setInterval(() => {
        send({ action: "presence.heartbeat", data: {} });
      }, HEARTBEAT_INTERVAL_MS);
    };

    ws.onmessage = (e) => {
      try {
        const frame = JSON.parse(e.data) as WsEvent;
        applyEvent(frame);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = () => {
      setConnected(false);
      if (heartbeatTimerRef.current != null) {
        window.clearInterval(heartbeatTimerRef.current);
        heartbeatTimerRef.current = null;
      }
      if (closedByUserRef.current) return;
      const attempt = reconnectAttemptRef.current;
      const delay = RECONNECT_DELAYS_MS[
        Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)
      ];
      reconnectAttemptRef.current = attempt + 1;
      window.setTimeout(connect, delay);
    };

    ws.onerror = () => {
      // onclose will fire next; nothing to do here.
    };
  }, [applyEvent, send, slug]);

  useEffect(() => {
    closedByUserRef.current = false;
    reconnectAttemptRef.current = 0;
    connect();
    return () => {
      closedByUserRef.current = true;
      if (heartbeatTimerRef.current != null) {
        window.clearInterval(heartbeatTimerRef.current);
      }
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
    };
  }, [connect]);

  const sendChat = useCallback(() => {
    // Flush any pending debounced update first so the committed draft
    // carries the latest local body.
    if (draftDebounceRef.current != null) {
      window.clearTimeout(draftDebounceRef.current);
      draftDebounceRef.current = null;
      if (pendingDraftBodyRef.current != null && stateRef.current.active_draft) {
        send({
          action: "draft.update",
          data: {
            version: stateRef.current.active_draft.version,
            body: pendingDraftBodyRef.current,
          },
        });
      }
    }
    pendingDraftBodyRef.current = null;
    send({ action: "chat.send", data: {} });
  }, [send]);

  const stopChat = useCallback(
    (messageId: number) => {
      send({ action: "chat.stop", data: { message_id: messageId } });
    },
    [send],
  );

  const updateDraft = useCallback(
    (body: string) => {
      // Optimistic local update so the textarea feels snappy.
      setState((prev) =>
        prev.active_draft
          ? { ...prev, active_draft: { ...prev.active_draft, body } }
          : prev,
      );
      pendingDraftBodyRef.current = body;
      if (draftDebounceRef.current != null) {
        window.clearTimeout(draftDebounceRef.current);
      }
      draftDebounceRef.current = window.setTimeout(() => {
        draftDebounceRef.current = null;
        const current = stateRef.current.active_draft;
        const pending = pendingDraftBodyRef.current;
        pendingDraftBodyRef.current = null;
        if (current != null && pending != null) {
          send({
            action: "draft.update",
            data: { version: current.version, body: pending },
          });
        }
      }, DRAFT_UPDATE_DEBOUNCE_MS);
    },
    [send],
  );

  const takeOverDraft = useCallback(() => {
    send({ action: "draft.take_over", data: {} });
  }, [send]);

  const discardDraft = useCallback(() => {
    send({ action: "draft.discard", data: {} });
  }, [send]);

  return {
    state,
    connected,
    sendChat,
    stopChat,
    updateDraft,
    takeOverDraft,
    discardDraft,
    lastError,
  };
}
