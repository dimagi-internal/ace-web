import { render, screen, waitFor } from "@testing-library/react";
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
    has_more_before: false,
    oldest_loaded_turn_index: null,
  }),
  listCanopyRunners: vi.fn().mockResolvedValue([]),
  placeCanopySession: vi.fn().mockResolvedValue(undefined),
  fetchOlderMessages: vi.fn().mockResolvedValue([]),
  attachCanopySession: vi.fn().mockResolvedValue(undefined),
  detachCanopySession: vi.fn().mockResolvedValue(undefined),
}));

import { useCanopyStatus } from "./useCanopyStatus";
import {
  getCanopySession,
  listCanopyRunners,
  placeCanopySession,
  attachCanopySession,
  detachCanopySession,
} from "./api";
import { getCanopyToken } from "./token";
import { CanopyChatPanel } from "./CanopyChatPanel";

const useCanopyStatusMock = vi.mocked(useCanopyStatus);
const getCanopySessionMock = vi.mocked(getCanopySession);
const listCanopyRunnersMock = vi.mocked(listCanopyRunners);
const placeCanopySessionMock = vi.mocked(placeCanopySession);
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
      has_more_before: false,
      oldest_loaded_turn_index: null,
    });
    listCanopyRunnersMock.mockResolvedValue([]);
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

  it("shows the placement banner when the bound runner is offline (lowercase wire status), and onPlace posts a placement", async () => {
    mockSocket();
    getCanopySessionMock.mockResolvedValue({
      id: "sess-1",
      title: "Chat",
      agent_slug: "echo",
      updated_at: "now",
      runner_name: "runner-a",
      has_more_before: false,
      oldest_loaded_turn_index: null,
    });
    listCanopyRunnersMock.mockResolvedValue([
      { id: "r-a", name: "runner-a", live_status: "stale", ready: false, capabilities: { sessions: true } },
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

  it("does not show a placement banner when the bound runner is online (lowercase wire status)", async () => {
    mockSocket();
    getCanopySessionMock.mockResolvedValue({
      id: "sess-1",
      title: "Chat",
      agent_slug: "echo",
      updated_at: "now",
      runner_name: "runner-a",
      has_more_before: false,
      oldest_loaded_turn_index: null,
    });
    listCanopyRunnersMock.mockResolvedValue([
      { id: "r-a", name: "runner-a", live_status: "online", ready: true, capabilities: { sessions: true } },
    ]);

    render(<CanopyChatPanel sessionId="sess-1" />);

    await waitFor(() => expect(listCanopyRunnersMock).toHaveBeenCalled());
    expect(screen.queryByText(/is unavailable/i)).not.toBeInTheDocument();
  });

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
});
