import { useCallback, useEffect, useRef, useState } from "react";

import type {
  Draft,
  Message,
  SessionState,
  WsEvent,
} from "../api/types";
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
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${base}/ws/sessions/${slug}/`;
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

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const send = useCallback((frame: { action: string; data: unknown }) => {
    const ws = socketRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(frame));
    }
  }, []);

  const applyEvent = useCallback((frame: WsEvent) => {
    // Side-effect events (no local state to mutate, but other surfaces
    // need to refresh). Handle BEFORE setState so React strict-mode's
    // double-invocation of the updater doesn't double-fire the event.
    if (frame.event === "session.title_updated") {
      // Tells RecentSessionsSidebar AND ChatPage's header to re-fetch.
      // Both already listen for this event for user-driven changes
      // (rename); piggy-backing the auto-title broadcast onto the same
      // channel keeps them consistent.
      notifySessionsUpdated();
      return;
    }
    setState((prev) => {
      switch (frame.event) {
        case "session.state":
          return frame.data;
        case "chat.stream_start": {
          // Flip the matching message to streaming if present.
          return {
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === frame.data.message_id
                ? { ...m, status: "streaming" as const }
                : m,
            ),
          };
        }
        case "chat.delta":
          return {
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === frame.data.message_id
                ? { ...m, plaintext: m.plaintext + frame.data.text }
                : m,
            ),
          };
        case "chat.stream_complete":
          return {
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === frame.data.message_id
                ? {
                    ...m,
                    plaintext: frame.data.plaintext,
                    status: "complete" as const,
                  }
                : m,
            ),
          };
        case "chat.stream_error":
          // NOTE: the backend emits chat.stream_error with detail="cancelled"
          // for stop-driven cancellation — there is no separate
          // chat.stream_cancelled event in practice. Handle both event
          // types here; the cancellation case is distinguished by
          // detail === "cancelled".
          return {
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === frame.data.message_id
                ? {
                    ...m,
                    status: "error" as const,
                    error_detail: frame.data.detail,
                  }
                : m,
            ),
          };
        case "chat.stream_cancelled":
          return {
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === frame.data.message_id
                ? {
                    ...m,
                    status: "error" as const,
                    error_detail: `cancelled (partial: ${frame.data.partial_len} chars)`,
                  }
                : m,
            ),
          };
        case "chat.tool_use":
        case "chat.tool_result":
          // Tool rows are their own Message rows on the server. A full
          // refresh picks them up; for now, don't duplicate bookkeeping
          // here. Task 12's ChatPage can re-fetch via listMessages if
          // needed for the tool render.
          return prev;
        case "draft.updated": {
          const incoming = frame.data as Draft;
          // If we're the current editor, keep our local body — the server
          // echo is stale relative to keystrokes that happened since the
          // debounced send. Only accept metadata (version, last_editor, etc).
          if (
            prev.active_draft &&
            incoming.last_editor === prev.current_user_id
          ) {
            return {
              ...prev,
              active_draft: {
                ...prev.active_draft,
                version: incoming.version,
                last_editor: incoming.last_editor,
                last_edit_at: incoming.last_edit_at,
              },
            };
          }
          return { ...prev, active_draft: incoming };
        }
        case "draft.lock_changed":
          if (prev.active_draft && prev.active_draft.id === frame.data.draft_id) {
            return {
              ...prev,
              active_draft: {
                ...prev.active_draft,
                last_editor: frame.data.holder_user_id ?? prev.active_draft.last_editor,
              },
            };
          }
          return prev;
        case "draft.committed": {
          // Insert the user message and an assistant placeholder into the
          // message list. The user message is constructed from the draft
          // body that's about to be cleared; the assistant placeholder is
          // filled in by chat.delta + chat.stream_complete events.
          //
          // This is load-bearing: without it, chat.stream_start's map over
          // prev.messages is a no-op (the new assistant message id isn't
          // in the list yet), and the assistant response is invisible
          // until the page refreshes.
          //
          // We also clear active_draft.body here. The server creates a new
          // empty draft with last_editor=sender, so the follow-up
          // draft.updated hits the "keep local body" branch below and would
          // otherwise leave the just-sent text in the textarea — which lets
          // Enter re-send the same turn repeatedly.
          const prevDraftBody = prev.active_draft?.body ?? "";
          const maxTurnIndex = prev.messages.reduce(
            (acc, msg) => Math.max(acc, msg.turn_index),
            0,
          );
          const nowIso = new Date().toISOString();
          const userMessage: Message = {
            id: frame.data.user_message_id,
            turn_index: maxTurnIndex + 1,
            role: "user",
            content: { text: prevDraftBody },
            plaintext: prevDraftBody,
            status: "complete",
            error_detail: null,
            started_at: null,
            completed_at: nowIso,
            created_at: nowIso,
          };
          const assistantPlaceholder: Message = {
            id: frame.data.message_id,
            turn_index: maxTurnIndex + 2,
            role: "assistant",
            content: {},
            plaintext: "",
            status: "pending",
            error_detail: null,
            started_at: null,
            completed_at: null,
            created_at: nowIso,
          };
          return {
            ...prev,
            active_draft: prev.active_draft
              ? { ...prev.active_draft, body: "" }
              : prev.active_draft,
            messages: [...prev.messages, userMessage, assistantPlaceholder],
          };
        }
        case "draft.discarded":
          if (prev.active_draft && prev.active_draft.id === frame.data.draft_id) {
            return {
              ...prev,
              active_draft: { ...prev.active_draft, body: "" },
            };
          }
          return prev;
        case "presence.joined": {
          const ids = new Set(prev.presence_user_ids);
          ids.add(frame.data.user_id);
          return { ...prev, presence_user_ids: [...ids] };
        }
        case "presence.left":
          return {
            ...prev,
            presence_user_ids: prev.presence_user_ids.filter(
              (id) => id !== frame.data.user_id,
            ),
          };
        case "session.error": {
          setLastError(frame.data.message);
          if (
            frame.data.code === "draft_version_mismatch" &&
            frame.data.detail &&
            typeof frame.data.detail === "object"
          ) {
            const detail = frame.data.detail as {
              current_version: number;
              current_body: string;
            };
            // Clear any pending optimistic body so the user's stale
            // local text doesn't auto-re-send with the new version.
            pendingDraftBodyRef.current = null;
            if (draftDebounceRef.current != null) {
              window.clearTimeout(draftDebounceRef.current);
              draftDebounceRef.current = null;
            }
            return prev.active_draft
              ? {
                  ...prev,
                  active_draft: {
                    ...prev.active_draft,
                    version: detail.current_version,
                    body: detail.current_body,
                  },
                }
              : prev;
          }
          return prev;
        }
        default:
          return prev;
      }
    });
  }, []);

  const connect = useCallback(() => {
    if (closedByUserRef.current) return;
    const ws = new WebSocket(wsUrlFor(slug));
    socketRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      reconnectAttemptRef.current = 0;
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
