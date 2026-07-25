import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * I5 round-2, item 3 (off-by-one regression). The `connectAttemptRef`
 * reset used to live in a `useEffect`, which fires AFTER the kit's own
 * mount effect (`useSessionSocket` calls `connect()` -> `wsUrl` inside an
 * effect registered earlier in this component's hook call order, since
 * `useSessionSocket()` is invoked before our reset effect in the source).
 * So on mount the counter went 0->1 during the real initial connect, and
 * the reset effect then clobbered it straight back to 0 — meaning the
 * actual FIRST reconnect looked identical to the initial connect, and
 * forcing only actually began on the SECOND reconnect (contradicting the
 * code's own comment).
 *
 * `CanopyChatPanel.test.tsx` mocks `useSessionSocket` entirely and drives
 * `wsUrl` manually, so it structurally cannot observe this effect-timing
 * race (the kit's mount effect never runs). This file uses the REAL
 * `canopy-ui/chat` hook against a controllable fake global `WebSocket`, so
 * the mount -> drop -> reconnect sequence is the real one React schedules.
 */

vi.mock("./useCanopyStatus", () => ({
  useCanopyStatus: () => ({
    enabled: true,
    base_url: "/canopy",
    workspace: "ws-1",
    agent: "echo",
  }),
}));

const getCanopyTokenMock = vi.fn().mockResolvedValue("tok");
vi.mock("./token", () => ({
  getCanopyToken: (...args: unknown[]) => getCanopyTokenMock(...args),
  peekCanopyToken: () => "tok",
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

import { CanopyChatPanel } from "./CanopyChatPanel";

/** Minimal controllable fake of the browser `WebSocket` — just enough for
 *  the kit's `useSessionSocket` to construct one, attach handlers, and
 *  have this test drive `onclose` to trigger its reconnect ladder. */
class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  url: string;
  readyState = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(): void {
    /* no-op: this test never exercises sendChat/heartbeat */
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }
}

describe("CanopyChatPanel — reconnect force-refresh off-by-one (round-2 regression)", () => {
  const OriginalWebSocket = global.WebSocket;

  beforeEach(() => {
    getCanopyTokenMock.mockClear();
    FakeWebSocket.instances = [];
    global.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
    global.WebSocket = OriginalWebSocket;
  });

  it("forces a token refresh on the FIRST reconnect after a drop, not the second", async () => {
    render(<CanopyChatPanel sessionId="sess-1" />);

    // Real mount: CanopyChatPanel's own gate mints a token, then
    // CanopyChatPanelBody mounts and useSessionSocket's real effect calls
    // connect() -> our wsUrl builder -> `new WebSocket(...)`.
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const callsAtInitialConnect = getCanopyTokenMock.mock.calls.length;
    expect(callsAtInitialConnect).toBeGreaterThan(0);
    // The MOST RECENT call at this point is the wsUrl builder's own —
    // isReconnect is false on a real initial connect.
    expect(getCanopyTokenMock.mock.calls[callsAtInitialConnect - 1]).toEqual([false]);

    // Simulate the bound socket dropping — the kit's own onclose handler
    // schedules a reconnect at RECONNECT_DELAYS_MS[0] = 1000ms.
    const first = FakeWebSocket.instances[0];
    first.onclose?.();
    await vi.advanceTimersByTimeAsync(1_000);

    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(2));
    const callsAtFirstReconnect = getCanopyTokenMock.mock.calls.length;
    expect(callsAtFirstReconnect).toBeGreaterThan(callsAtInitialConnect);
    // This is the actual FIRST reconnect attempt. Before the fix, the
    // reset-via-useEffect race made this come back `false` (forcing only
    // started on the SECOND reconnect); it must be `true`.
    expect(getCanopyTokenMock.mock.calls[callsAtFirstReconnect - 1]).toEqual([true]);
  });
});
