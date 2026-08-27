import { act, render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionState } from "canopy-ui/chat";

/**
 * CanopyChatPanel is the ace-web twin of canopy-web's own ChatPage
 * container (frontend/src/pages/ChatPage.tsx there): it wires the kit's
 * `useSessionSocket` + `ChatPanel` + `PlacementBanner` together with
 * ace-side seams (canopy REST client, ace's markdown renderer). The kit
 * itself (`canopy-ui/chat`) is exercised elsewhere (its own package tests);
 * here we mock `useSessionSocket` so we control the socket state precisely,
 * and assert CanopyChatPanel wires it into `ChatPanel`/`PlacementBanner`
 * correctly.
 *
 * Fix-round-1 note: runner-status fixtures below use the REAL lowercase
 * wire values (`"online"`/`"stale"` — `apps/harness/models.py`'s
 * `Runner.live_status` constants), not the Python constant NAMES. An
 * earlier draft used `"ONLINE"`/`"OFFLINE"` fixtures, which is exactly how
 * a case-mismatch bug (comparing against the constant's name instead of
 * its value) slipped through review undetected.
 *
 * Fix-round-2 note: the offline-runner banner is now driven by the session
 * detail's `runner_online` field, NOT by matching `runner_name` against
 * `listCanopyRunners()` — that endpoint is scoped to runners the CALLER
 * personally paired, so a delegated ace user sees an empty fleet there
 * regardless of whether the session's actual bound runner is up or down.
 */

const sessionSocketMock = vi.fn();
const stopChatMock = vi.fn();

vi.mock("canopy-ui/chat", async () => {
  const actual = await vi.importActual<typeof import("canopy-ui/chat")>("canopy-ui/chat");
  return {
    ...actual,
    useSessionSocket: (...args: unknown[]) => sessionSocketMock(...args),
  };
});

vi.mock("./useCanopyStatus", () => ({
  useCanopyStatus: vi.fn(),
}));

vi.mock("./token", () => ({
  getCanopyToken: vi.fn().mockResolvedValue("tok"),
  peekCanopyToken: vi.fn().mockReturnValue("tok"),
}));

vi.mock("./api", () => ({
  RUNNER_STATUS_ONLINE: "online",
  getCanopySession: vi.fn().mockResolvedValue({
    id: "sess-1",
    title: "Chat",
    agent_slug: null,
    updated_at: "now",
    runner_name: null,
    runner_online: null,
    has_more_before: false,
    oldest_loaded_turn_index: null,
  }),
  listCanopyRunners: vi.fn().mockResolvedValue([]),
  placeCanopySession: vi.fn().mockResolvedValue(undefined),
  fetchOlderMessages: vi.fn().mockResolvedValue({ messages: [], has_more_before: false }),
  attachCanopySession: vi.fn().mockResolvedValue(undefined),
  detachCanopySession: vi.fn().mockResolvedValue(undefined),
}));

import { useCanopyStatus } from "./useCanopyStatus";
import {
  getCanopySession,
  listCanopyRunners,
  placeCanopySession,
  fetchOlderMessages,
  attachCanopySession,
  detachCanopySession,
} from "./api";
import { getCanopyToken } from "./token";
import { CanopyChatPanel } from "./CanopyChatPanel";

const useCanopyStatusMock = vi.mocked(useCanopyStatus);
const getCanopySessionMock = vi.mocked(getCanopySession);
const listCanopyRunnersMock = vi.mocked(listCanopyRunners);
const placeCanopySessionMock = vi.mocked(placeCanopySession);
const fetchOlderMessagesMock = vi.mocked(fetchOlderMessages);
const attachCanopySessionMock = vi.mocked(attachCanopySession);
const detachCanopySessionMock = vi.mocked(detachCanopySession);
const getCanopyTokenMock = vi.mocked(getCanopyToken);

function baseState(overrides: Partial<SessionState> = {}): SessionState {
  return {
    messages: [],
    active_draft: null,
    participants: [],
    presence_user_ids: [],
    current_user_id: 42,
    ...overrides,
  };
}

function mockSocket(overrides: Partial<ReturnType<typeof sessionSocketMock>> = {}) {
  const result = {
    state: baseState(),
    connected: true,
    sendChat: vi.fn(),
    stopChat: stopChatMock,
    updateDraft: vi.fn(),
    takeOverDraft: vi.fn(),
    discardDraft: vi.fn(),
    prependMessages: vi.fn(),
    lastError: null,
    ...overrides,
  };
  sessionSocketMock.mockReturnValue(result);
  return result;
}

describe("CanopyChatPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useCanopyStatusMock.mockReturnValue({
      enabled: true,
      base_url: "/canopy",
      workspace: "ws-1",
      agent: "echo",
    });
    getCanopySessionMock.mockResolvedValue({
      id: "sess-1",
      title: "Chat",
      agent_slug: null,
      updated_at: "now",
      runner_name: null,
      runner_online: null,
      has_more_before: false,
      oldest_loaded_turn_index: null,
    });
    listCanopyRunnersMock.mockResolvedValue([]);
    fetchOlderMessagesMock.mockResolvedValue({ messages: [], has_more_before: false });
  });

  it("shows a Connecting… shell until status + token are ready, then renders the wired ChatPanel", async () => {
    mockSocket({
      state: baseState({
        current_user_id: 7,
        messages: [
          {
            id: "m1",
            turn_index: 0,
            role: "user",
            content: {},
            plaintext: "hello",
            status: "complete",
            error_detail: null,
            started_at: null,
            completed_at: "2026-07-25T00:00:00Z",
            created_at: "2026-07-25T00:00:00Z",
          },
        ],
      }),
    });

    render(<CanopyChatPanel sessionId="sess-1" />);

    // Renders once status + the token mint have settled.
    await screen.findByText("hello");
    expect(sessionSocketMock).toHaveBeenCalledWith(
      expect.objectContaining({ sessionId: "sess-1" }),
    );
  });

  it("renders the Connecting… shell (not the socket) while useCanopyStatus is still null", async () => {
    useCanopyStatusMock.mockReturnValue(null);
    mockSocket();

    render(<CanopyChatPanel sessionId="sess-1" />);

    expect(screen.getByText(/connecting/i)).toBeInTheDocument();
    expect(sessionSocketMock).not.toHaveBeenCalled();
    // Let the (still-warming, since status hasn't resolved) token-mint
    // effect settle so its state update lands inside this test's act().
    await waitFor(() => expect(getCanopyTokenMock).toHaveBeenCalled());
  });

  it("calls the kit's stopChat when onStop fires", async () => {
    mockSocket({
      state: baseState({
        messages: [
          {
            id: "m1",
            turn_index: 0,
            role: "assistant",
            content: {},
            plaintext: "working…",
            status: "streaming",
            error_detail: null,
            started_at: null,
            completed_at: null,
            created_at: "2026-07-25T00:00:00Z",
          },
        ],
      }),
    });

    render(<CanopyChatPanel sessionId="sess-1" />);

    const stopButton = await screen.findByRole("button", { name: /stop/i });
    fireEvent.click(stopButton);

    expect(stopChatMock).toHaveBeenCalledWith("m1");
  });

  it("attaches on mount and detaches on unmount (viewer-liveness pair)", async () => {
    mockSocket();

    const { unmount } = render(<CanopyChatPanel sessionId="sess-1" />);

    await waitFor(() => expect(attachCanopySessionMock).toHaveBeenCalledWith("/canopy", "sess-1"));
    expect(detachCanopySessionMock).not.toHaveBeenCalled();

    unmount();

    await waitFor(() => expect(detachCanopySessionMock).toHaveBeenCalledWith("/canopy", "sess-1"));
  });

  // --- I5: forced token refresh on reconnect --------------------------------

  it("does NOT force a token refresh on the initial connect", async () => {
    mockSocket();
    render(<CanopyChatPanel sessionId="sess-1" />);

    await waitFor(() => expect(sessionSocketMock).toHaveBeenCalled());
    const { wsUrl } = sessionSocketMock.mock.calls[0][0] as { wsUrl: (p: string) => string };
    getCanopyTokenMock.mockClear();

    wsUrl("/ws/canopy-sessions/sess-1/");

    expect(getCanopyTokenMock).toHaveBeenCalledWith(false);
  });

  it("forces a token refresh on every reconnect attempt after the first (I5)", async () => {
    mockSocket();
    render(<CanopyChatPanel sessionId="sess-1" />);

    await waitFor(() => expect(sessionSocketMock).toHaveBeenCalled());
    const { wsUrl } = sessionSocketMock.mock.calls[0][0] as { wsUrl: (p: string) => string };
    getCanopyTokenMock.mockClear();

    // The kit calls the builder once per (re)connect attempt. The first
    // post-mount call here simulates the FIRST reconnect (a dropped
    // socket) — this is the "after the first failure" case I5 targets.
    wsUrl("/ws/canopy-sessions/sess-1/");
    wsUrl("/ws/canopy-sessions/sess-1/");

    expect(getCanopyTokenMock).toHaveBeenNthCalledWith(1, false);
    expect(getCanopyTokenMock).toHaveBeenNthCalledWith(2, true);
  });

  it("does not produce an unhandled rejection when a reconnect's mint fails (round-2 review)", async () => {
    mockSocket();
    render(<CanopyChatPanel sessionId="sess-1" />);

    await waitFor(() => expect(sessionSocketMock).toHaveBeenCalled());
    const { wsUrl } = sessionSocketMock.mock.calls[0][0] as { wsUrl: (p: string) => string };
    getCanopyTokenMock.mockClear();
    getCanopyTokenMock.mockRejectedValueOnce(new Error("canopy down"));

    const unhandled = vi.fn();
    process.on("unhandledRejection", unhandled);
    try {
      // Whichever call this is (initial connect or a reconnect), its mint
      // rejects — before the `.catch()` fix this was a fire-and-forget
      // `void getCanopyToken(...)` with no handler, which is exactly an
      // unhandled promise rejection once the promise actually settles.
      wsUrl("/ws/canopy-sessions/sess-1/");
      // Flush microtasks so the rejected promise's continuation (or lack of
      // one) has a chance to surface as an unhandled rejection.
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    } finally {
      process.off("unhandledRejection", unhandled);
    }
    expect(unhandled).not.toHaveBeenCalled();
  });

  it("throttles forced refreshes on a flapping reconnect to at most one per 30s", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockSocket();
      render(<CanopyChatPanel sessionId="sess-1" />);

      await vi.waitFor(() => expect(sessionSocketMock).toHaveBeenCalled());
      const { wsUrl } = sessionSocketMock.mock.calls[0][0] as { wsUrl: (p: string) => string };
      getCanopyTokenMock.mockClear();

      wsUrl("/ws/canopy-sessions/sess-1/"); // initial connect
      wsUrl("/ws/canopy-sessions/sess-1/"); // reconnect #1 -> forces
      wsUrl("/ws/canopy-sessions/sess-1/"); // reconnect #2, immediately after -> throttled
      wsUrl("/ws/canopy-sessions/sess-1/"); // reconnect #3, immediately after -> still throttled

      expect(getCanopyTokenMock).toHaveBeenNthCalledWith(1, false);
      expect(getCanopyTokenMock).toHaveBeenNthCalledWith(2, true);
      expect(getCanopyTokenMock).toHaveBeenNthCalledWith(3, false);
      expect(getCanopyTokenMock).toHaveBeenNthCalledWith(4, false);

      await vi.advanceTimersByTimeAsync(30_000);
      wsUrl("/ws/canopy-sessions/sess-1/"); // reconnect #4, past the throttle window -> forces again

      expect(getCanopyTokenMock).toHaveBeenNthCalledWith(5, true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a non-forced (throttled) reconnect still reads the token cache normally, unaffected by the throttle", async () => {
    // I5 round 2: "non-forced cached reads must stay unaffected" — the
    // throttle only ever changes the `force` argument passed to
    // getCanopyToken; it never skips calling it, so a still-valid cached
    // token is served exactly as it would be outside a reconnect storm.
    mockSocket();
    render(<CanopyChatPanel sessionId="sess-1" />);

    await waitFor(() => expect(sessionSocketMock).toHaveBeenCalled());
    const { wsUrl } = sessionSocketMock.mock.calls[0][0] as { wsUrl: (p: string) => string };
    getCanopyTokenMock.mockClear();

    wsUrl("/ws/canopy-sessions/sess-1/"); // initial connect -> false
    wsUrl("/ws/canopy-sessions/sess-1/"); // reconnect #1 -> forces (true)
    wsUrl("/ws/canopy-sessions/sess-1/"); // reconnect #2, throttled -> false, but still CALLED

    expect(getCanopyTokenMock).toHaveBeenCalledTimes(3);
    expect(getCanopyTokenMock).toHaveBeenNthCalledWith(3, false);
  });

  // --- offline-runner banner: driven by session detail's runner_online -----

  it("shows the placement banner when the session detail reports runner_online: false, and onPlace posts a placement (fleet non-empty)", async () => {
    mockSocket();
    getCanopySessionMock.mockResolvedValue({
      id: "sess-1",
      title: "Chat",
      agent_slug: "echo",
      updated_at: "now",
      runner_name: "runner-a",
      runner_online: false,
      has_more_before: false,
      oldest_loaded_turn_index: null,
    });
    listCanopyRunnersMock.mockResolvedValue([
      { id: "r-b", name: "runner-b", live_status: "online", ready: true, capabilities: { sessions: true } },
    ]);

    render(<CanopyChatPanel sessionId="sess-1" />);

    await screen.findByText(/runner-a is unavailable/i);

    fireEvent.click(screen.getByRole("button", { name: /continue on/i }));
    fireEvent.change(screen.getByLabelText(/continue on/i), { target: { value: "r-b" } });

    await waitFor(() => {
      expect(placeCanopySessionMock).toHaveBeenCalledWith("/canopy", "sess-1", {
        runner_id: "r-b",
      });
    });
  });

  it("degrades to a plain 'wait for it' banner (no picker) when runner_online is false but the fleet list is empty — the common delegated-user case", async () => {
    mockSocket();
    getCanopySessionMock.mockResolvedValue({
      id: "sess-1",
      title: "Chat",
      agent_slug: "echo",
      updated_at: "now",
      runner_name: "runner-a",
      runner_online: false,
      has_more_before: false,
      oldest_loaded_turn_index: null,
    });
    listCanopyRunnersMock.mockResolvedValue([]); // scoped-to-caller fleet: empty

    render(<CanopyChatPanel sessionId="sess-1" />);

    await screen.findByText(/runner-a is unavailable/i);

    expect(screen.queryByRole("button", { name: /continue on/i })).not.toBeInTheDocument();
    const waitButton = screen.getByRole("button", { name: /wait for it/i });

    fireEvent.click(waitButton);

    await waitFor(() => {
      expect(placeCanopySessionMock).toHaveBeenCalledWith("/canopy", "sess-1", "wait");
    });
  });

  it("does not show a placement banner when runner_online is true", async () => {
    mockSocket();
    getCanopySessionMock.mockResolvedValue({
      id: "sess-1",
      title: "Chat",
      agent_slug: "echo",
      updated_at: "now",
      runner_name: "runner-a",
      runner_online: true,
      has_more_before: false,
      oldest_loaded_turn_index: null,
    });

    render(<CanopyChatPanel sessionId="sess-1" />);

    await waitFor(() => expect(getCanopySessionMock).toHaveBeenCalled());
    expect(screen.queryByText(/is unavailable/i)).not.toBeInTheDocument();
  });

  it("does not show a placement banner when runner_online is null (no binding)", async () => {
    mockSocket();
    getCanopySessionMock.mockResolvedValue({
      id: "sess-1",
      title: "Chat",
      agent_slug: "echo",
      updated_at: "now",
      runner_name: null,
      runner_online: null,
      has_more_before: false,
      oldest_loaded_turn_index: null,
    });

    render(<CanopyChatPanel sessionId="sess-1" />);

    await waitFor(() => expect(getCanopySessionMock).toHaveBeenCalled());
    expect(screen.queryByText(/is unavailable/i)).not.toBeInTheDocument();
  });

  it("re-polls the SESSION DETAIL (not the runner fleet) while offline, so the banner clears when the runner returns", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockSocket();
      getCanopySessionMock.mockResolvedValueOnce({
        id: "sess-1",
        title: "Chat",
        agent_slug: "echo",
        updated_at: "now",
        runner_name: "runner-a",
        runner_online: false,
        has_more_before: false,
        oldest_loaded_turn_index: null,
      });

      render(<CanopyChatPanel sessionId="sess-1" />);

      await vi.waitFor(() => expect(screen.getByText(/runner-a is unavailable/i)).toBeInTheDocument());
      const callsBeforePoll = getCanopySessionMock.mock.calls.length;

      getCanopySessionMock.mockResolvedValue({
        id: "sess-1",
        title: "Chat",
        agent_slug: "echo",
        updated_at: "now",
        runner_name: "runner-a",
        runner_online: true,
        has_more_before: false,
        oldest_loaded_turn_index: null,
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });

      expect(getCanopySessionMock.mock.calls.length).toBeGreaterThan(callsBeforePoll);
      await vi.waitFor(() =>
        expect(screen.queryByText(/is unavailable/i)).not.toBeInTheDocument(),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  // --- Ledger minor: fetchOlderMessages's own has_more_before is threaded --

  it("seeds hasMoreBefore from the session detail's real has_more_before (not a hardcoded true)", async () => {
    mockSocket({
      state: baseState({
        messages: [
          {
            id: "m1",
            turn_index: 5,
            role: "user",
            content: {},
            plaintext: "hi",
            status: "complete",
            error_detail: null,
            started_at: null,
            completed_at: "now",
            created_at: "now",
          },
        ],
      }),
    });
    getCanopySessionMock.mockResolvedValue({
      id: "sess-1",
      title: "Chat",
      agent_slug: null,
      updated_at: "now",
      runner_name: null,
      runner_online: null,
      has_more_before: false,
      oldest_loaded_turn_index: null,
    });

    render(<CanopyChatPanel sessionId="sess-1" />);

    await screen.findByText("hi");
    await waitFor(() => expect(getCanopySessionMock).toHaveBeenCalledWith("/canopy", "sess-1"));
    // has_more_before: false → no "Load earlier" button, even though a
    // message is already loaded (the old hardcoded-true seed would show it).
    expect(screen.queryByRole("button", { name: /load earlier/i })).not.toBeInTheDocument();
  });

  it("updates hasMoreBefore from the page's OWN has_more_before after loading earlier history, not from messages.length", async () => {
    const prepended: unknown[] = [];
    mockSocket({
      state: baseState({
        messages: [
          {
            id: "m1",
            turn_index: 5,
            role: "user",
            content: {},
            plaintext: "hi",
            status: "complete",
            error_detail: null,
            started_at: null,
            completed_at: "now",
            created_at: "now",
          },
        ],
      }),
      prependMessages: vi.fn((msgs: unknown[]) => prepended.push(...msgs)),
    });
    getCanopySessionMock.mockResolvedValue({
      id: "sess-1",
      title: "Chat",
      agent_slug: null,
      updated_at: "now",
      runner_name: null,
      runner_online: null,
      has_more_before: true,
      oldest_loaded_turn_index: null,
    });
    // Page comes back non-empty but STILL says there's more before it — a
    // hardcoded "messages.length === 0 -> no more" inference would get this
    // wrong.
    fetchOlderMessagesMock.mockResolvedValue({
      messages: [
        {
          turn_index: 4,
          role: "user",
          content: {},
          plaintext: "earlier",
          created_at: "now",
        },
      ],
      has_more_before: true,
    });

    render(<CanopyChatPanel sessionId="sess-1" />);

    const loadEarlierButton = await screen.findByRole("button", { name: /load earlier/i });
    fireEvent.click(loadEarlierButton);

    await waitFor(() => expect(fetchOlderMessagesMock).toHaveBeenCalledWith("/canopy", "sess-1", 5));
    // Still present — has_more_before stayed true on the response.
    expect(await screen.findByRole("button", { name: /load earlier/i })).toBeInTheDocument();
  });
});
