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
  listCanopySessions: vi.fn().mockResolvedValue([]),
  listCanopyRunners: vi.fn().mockResolvedValue([]),
  placeCanopySession: vi.fn().mockResolvedValue(undefined),
  fetchOlderMessages: vi.fn().mockResolvedValue([]),
}));

import { useCanopyStatus } from "./useCanopyStatus";
import { listCanopySessions, listCanopyRunners, placeCanopySession } from "./api";
import { CanopyChatPanel } from "./CanopyChatPanel";

const useCanopyStatusMock = vi.mocked(useCanopyStatus);
const listCanopySessionsMock = vi.mocked(listCanopySessions);
const listCanopyRunnersMock = vi.mocked(listCanopyRunners);
const placeCanopySessionMock = vi.mocked(placeCanopySession);

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
    listCanopySessionsMock.mockResolvedValue([]);
    listCanopyRunnersMock.mockResolvedValue([]);
  });

  it("renders and wires ChatPanel from the mocked socket state", async () => {
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

    expect(sessionSocketMock).toHaveBeenCalledWith(
      expect.objectContaining({ sessionId: "sess-1" }),
    );
    expect(screen.getByText("hello")).toBeInTheDocument();
    // Let the (irrelevant to this test) session/runner-fleet lookups settle.
    await waitFor(() => expect(listCanopySessionsMock).toHaveBeenCalled());
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

    const stopButton = screen.getByRole("button", { name: /stop/i });
    fireEvent.click(stopButton);

    expect(stopChatMock).toHaveBeenCalledWith("m1");
    // Let the (irrelevant to this test) session/runner-fleet lookups settle.
    await waitFor(() => expect(listCanopySessionsMock).toHaveBeenCalled());
  });

  it("shows the placement banner when the bound runner is offline, and onPlace posts a placement", async () => {
    mockSocket();
    listCanopySessionsMock.mockResolvedValue([
      { id: "sess-1", title: "Chat", agent_slug: "echo", updated_at: "now", runner_name: "runner-a" },
    ]);
    listCanopyRunnersMock.mockResolvedValue([
      { id: "r-a", name: "runner-a", live_status: "OFFLINE", ready: false, capabilities: { sessions: true } },
      { id: "r-b", name: "runner-b", live_status: "ONLINE", ready: true, capabilities: { sessions: true } },
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

  it("does not show a placement banner when the bound runner is online", async () => {
    mockSocket();
    listCanopySessionsMock.mockResolvedValue([
      { id: "sess-1", title: "Chat", agent_slug: "echo", updated_at: "now", runner_name: "runner-a" },
    ]);
    listCanopyRunnersMock.mockResolvedValue([
      { id: "r-a", name: "runner-a", live_status: "ONLINE", ready: true, capabilities: { sessions: true } },
    ]);

    render(<CanopyChatPanel sessionId="sess-1" />);

    await waitFor(() => expect(listCanopyRunnersMock).toHaveBeenCalled());
    expect(screen.queryByText(/is unavailable/i)).not.toBeInTheDocument();
  });
});
