import type { Draft, Message, SessionState, WsEvent } from "../api/types";

// Pure reducer for SessionState — extracted from useSessionSocket so it
// can be unit-tested without WebSocket plumbing. Side-effect events
// (session.title_updated → notifySessionsUpdated; session.error →
// setLastError + clear draft debounce) stay in the hook itself.
//
// Keep this file dependency-free (no React, no api/types imports beyond
// the type-only ones above) so a vitest run doesn't pull jsdom or RTL.
export function sessionReducer(prev: SessionState, frame: WsEvent): SessionState {
  switch (frame.event) {
    case "session.state":
      return frame.data;

    case "chat.stream_start":
      return {
        ...prev,
        messages: prev.messages.map((m) =>
          m.id === frame.data.message_id
            ? { ...m, status: "streaming" as const }
            : m,
        ),
      };

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
      // NOTE: backend emits chat.stream_error with detail="cancelled"
      // for stop-driven cancellation; there's no separate
      // chat.stream_cancelled event in practice. Distinguished by detail.
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
      // refresh picks them up; for now, don't duplicate bookkeeping here.
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
      // Load-bearing: without it, chat.stream_start's map over
      // prev.messages is a no-op (the new assistant message id isn't
      // in the list yet), and the assistant response is invisible
      // until the page refreshes.
      //
      // Also clear active_draft.body here. The server creates a new
      // empty draft with last_editor=sender, so the follow-up
      // draft.updated hits the "keep local body" branch above and would
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
      // Side effects (setLastError, clear draft debounce) are handled
      // by the hook; the reducer only knows about the version-mismatch
      // recovery, which mutates active_draft.
      if (
        frame.data.code === "draft_version_mismatch" &&
        frame.data.detail &&
        typeof frame.data.detail === "object"
      ) {
        const detail = frame.data.detail as {
          current_version: number;
          current_body: string;
        };
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

    case "session.title_updated":
      // Pure reducer leaves this alone — the hook calls
      // notifySessionsUpdated() on receipt and short-circuits. Included
      // here so an exhaustive switch type-checks.
      return prev;

    default:
      return prev;
  }
}
