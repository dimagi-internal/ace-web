import { describe, expect, it } from "vitest"

import type { Draft, Message, SessionState, WsEvent } from "../api/types.ws"
import { sessionReducer } from "./sessionReducer"

const baseDraft: Draft = {
  id: 1,
  slot: "next",
  status: "open",
  body: "",
  version: 0,
  last_editor: 0,
  last_edit_at: "",
}

function makeState(overrides: Partial<SessionState> = {}): SessionState {
  return {
    messages: [],
    active_draft: null,
    participants: [],
    presence_user_ids: [],
    current_user_id: 0,
    ...overrides,
  }
}

function makeMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: 1,
    turn_index: 1,
    role: "assistant",
    content: {},
    plaintext: "",
    status: "pending",
    error_detail: null,
    started_at: null,
    completed_at: null,
    created_at: new Date().toISOString(),
    ...overrides,
  }
}

describe("sessionReducer — chat stream", () => {
  it("session.state replaces the whole state", () => {
    const prev = makeState({ messages: [makeMessage()] })
    const replacement = makeState({ current_user_id: 42 })
    const next = sessionReducer(prev, {
      event: "session.state",
      data: replacement,
    } as WsEvent)
    expect(next).toBe(replacement)
  })

  it("chat.stream_start flips matching message to streaming", () => {
    const m = makeMessage({ id: 7, status: "pending" })
    const prev = makeState({ messages: [m] })
    const next = sessionReducer(prev, {
      event: "chat.stream_start",
      data: { message_id: 7 },
    } as WsEvent)
    expect(next.messages[0].status).toBe("streaming")
  })

  it("chat.stream_start ignores unknown message_id", () => {
    const m = makeMessage({ id: 7, status: "pending" })
    const prev = makeState({ messages: [m] })
    const next = sessionReducer(prev, {
      event: "chat.stream_start",
      data: { message_id: 99 },
    } as WsEvent)
    expect(next.messages[0].status).toBe("pending")
  })

  it("chat.delta appends text to plaintext", () => {
    const m = makeMessage({ id: 7, plaintext: "Hello" })
    const prev = makeState({ messages: [m] })
    const next = sessionReducer(prev, {
      event: "chat.delta",
      data: { message_id: 7, text: " world" },
    } as WsEvent)
    expect(next.messages[0].plaintext).toBe("Hello world")
  })

  it("chat.stream_complete replaces plaintext and marks complete", () => {
    const m = makeMessage({ id: 7, plaintext: "stale partial", status: "streaming" })
    const prev = makeState({ messages: [m] })
    const next = sessionReducer(prev, {
      event: "chat.stream_complete",
      data: { message_id: 7, plaintext: "final answer" },
    } as WsEvent)
    expect(next.messages[0].plaintext).toBe("final answer")
    expect(next.messages[0].status).toBe("complete")
  })

  it("chat.stream_error sets error_detail and status=error", () => {
    const m = makeMessage({ id: 7, status: "streaming" })
    const prev = makeState({ messages: [m] })
    const next = sessionReducer(prev, {
      event: "chat.stream_error",
      data: { message_id: 7, detail: "cancelled" },
    } as WsEvent)
    expect(next.messages[0].status).toBe("error")
    expect(next.messages[0].error_detail).toBe("cancelled")
  })

  it("chat.stream_cancelled stamps a partial-length detail", () => {
    const m = makeMessage({ id: 7, status: "streaming" })
    const prev = makeState({ messages: [m] })
    const next = sessionReducer(prev, {
      event: "chat.stream_cancelled",
      data: { message_id: 7, partial_len: 142 },
    } as WsEvent)
    expect(next.messages[0].status).toBe("error")
    expect(next.messages[0].error_detail).toMatch(/142/)
  })

  it("chat.tool_use is a no-op", () => {
    const prev = makeState({ messages: [makeMessage()] })
    const next = sessionReducer(prev, {
      event: "chat.tool_use",
      data: {},
    } as WsEvent)
    expect(next).toBe(prev)
  })
})

describe("sessionReducer — drafts", () => {
  it("draft.updated keeps local body when echo's last_editor matches current_user_id", () => {
    // Echo-suppression: server echo arrives stale relative to the user's
    // own keystrokes; reducer must keep the local body and only accept
    // metadata. This is the most subtle branch in the file.
    const prev = makeState({
      current_user_id: 5,
      active_draft: { ...baseDraft, body: "local typing", version: 3 },
    })
    const next = sessionReducer(prev, {
      event: "draft.updated",
      data: {
        ...baseDraft,
        body: "stale server echo",
        last_editor: 5,
        version: 3,
      } as Draft,
    } as WsEvent)
    expect(next.active_draft?.body).toBe("local typing")
    expect(next.active_draft?.version).toBe(3)
  })

  it("draft.updated accepts the body when another user is editing", () => {
    const prev = makeState({
      current_user_id: 5,
      active_draft: { ...baseDraft, body: "old", last_editor: 7 },
    })
    const next = sessionReducer(prev, {
      event: "draft.updated",
      data: {
        ...baseDraft,
        body: "their text",
        last_editor: 7,
        version: 2,
      } as Draft,
    } as WsEvent)
    expect(next.active_draft?.body).toBe("their text")
  })

  it("draft.committed inserts user message and assistant placeholder", () => {
    const prev = makeState({
      active_draft: { ...baseDraft, body: "the prompt" },
      messages: [makeMessage({ id: 1, turn_index: 1 })],
    })
    const next = sessionReducer(prev, {
      event: "draft.committed",
      data: { user_message_id: 100, message_id: 101, draft_id: 1 },
    } as WsEvent)
    expect(next.messages).toHaveLength(3)
    expect(next.messages[1]).toMatchObject({
      id: 100,
      role: "user",
      plaintext: "the prompt",
      turn_index: 2,
    })
    expect(next.messages[2]).toMatchObject({
      id: 101,
      role: "assistant",
      plaintext: "",
      status: "pending",
      turn_index: 3,
    })
    // active_draft.body cleared so Enter doesn't re-send the same turn.
    expect(next.active_draft?.body).toBe("")
  })

  it("draft.discarded clears matching draft body", () => {
    const prev = makeState({
      active_draft: { ...baseDraft, id: 1, body: "draft text" },
    })
    const next = sessionReducer(prev, {
      event: "draft.discarded",
      data: { draft_id: 1 },
    } as WsEvent)
    expect(next.active_draft?.body).toBe("")
  })
})

describe("sessionReducer — presence", () => {
  it("presence.joined adds a user_id idempotently", () => {
    const prev = makeState({ presence_user_ids: [1, 2] })
    const next = sessionReducer(prev, {
      event: "presence.joined",
      data: { user_id: 3 },
    } as WsEvent)
    expect(next.presence_user_ids.sort()).toEqual([1, 2, 3])

    // Second join is a no-op (Set semantics).
    const after = sessionReducer(next, {
      event: "presence.joined",
      data: { user_id: 3 },
    } as WsEvent)
    expect(after.presence_user_ids.filter((id) => id === 3)).toHaveLength(1)
  })

  it("presence.left filters out the user_id", () => {
    const prev = makeState({ presence_user_ids: [1, 2, 3] })
    const next = sessionReducer(prev, {
      event: "presence.left",
      data: { user_id: 2 },
    } as WsEvent)
    expect(next.presence_user_ids).toEqual([1, 3])
  })
})

describe("sessionReducer — session.error draft_version_mismatch", () => {
  it("rolls active_draft back to the server's reported version + body", () => {
    const prev = makeState({
      active_draft: { ...baseDraft, version: 9, body: "stale local" },
    })
    const next = sessionReducer(prev, {
      event: "session.error",
      data: {
        message: "version mismatch",
        code: "draft_version_mismatch",
        detail: { current_version: 11, current_body: "server body" },
      },
    } as WsEvent)
    expect(next.active_draft?.version).toBe(11)
    expect(next.active_draft?.body).toBe("server body")
  })

  it("non-version-mismatch errors are no-ops to state (side-effect handled by hook)", () => {
    const prev = makeState({
      active_draft: { ...baseDraft, body: "x" },
    })
    const next = sessionReducer(prev, {
      event: "session.error",
      data: { message: "something else", code: "other" },
    } as WsEvent)
    expect(next).toBe(prev)
  })
})

describe("sessionReducer — session.title_updated", () => {
  it("is a no-op for state (side-effect handled by hook)", () => {
    const prev = makeState({ messages: [makeMessage()] })
    const next = sessionReducer(prev, {
      event: "session.title_updated",
      data: { title: "new title" },
    } as WsEvent)
    expect(next).toBe(prev)
  })
})
