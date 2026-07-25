import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useOppSocket } from "../useOppSocket";

/**
 * Mock WebSocket mirroring the browser contract the bug depends on:
 * `close()` is asynchronous — the `onclose` event fires on a later tick,
 * potentially AFTER a replacement socket has already been opened.
 */
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static OPEN = 1;

  url: string;
  readyState = 0; // CONNECTING
  sent: string[] = [];
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code?: number }) => void) | null = null;
  onopen: ((e: unknown) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string) {
    if (this.readyState !== 1) throw new Error("InvalidStateError: not open");
    this.sent.push(data);
  }

  close() {
    // Real browsers fire onclose asynchronously — tests trigger it
    // explicitly via triggerClose() to control the ordering.
    this.readyState = 2; // CLOSING
  }

  triggerOpen() {
    this.readyState = 1;
    this.onopen?.({});
  }

  triggerClose(code = 1005) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.stubGlobal("WebSocket", MockWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useOppSocket", () => {
  it("sends decision.edit over the open socket", () => {
    const { result } = renderHook(() =>
      useOppSocket({ slug: "my-opp", runId: "run-1" }),
    );
    const ws = MockWebSocket.instances[0];
    act(() => ws.triggerOpen());

    act(() => result.current.sendDecisionEdit("row-1", "answer"));

    expect(ws.sent).toHaveLength(1);
    expect(JSON.parse(ws.sent[0])).toMatchObject({
      type: "decision.edit",
      row_id: "row-1",
      new_answer: "answer",
    });
  });

  it("keeps sending after the run resolves — a stale socket's late close must not clobber the live ref", () => {
    // The production entry path: page mounts with runId undefined (URL has
    // no ?run_id yet), the snapshot resolves, runId flips to a real value.
    const { result, rerender } = renderHook(
      ({ runId }: { runId?: string }) => useOppSocket({ slug: "my-opp", runId }),
      { initialProps: { runId: undefined as string | undefined } },
    );
    const unscoped = MockWebSocket.instances[0];
    act(() => unscoped.triggerOpen());

    // runId resolves → effect cleanup closes the unscoped socket and a
    // run-scoped socket opens.
    rerender({ runId: "run-1" });
    const scoped = MockWebSocket.instances[1];
    expect(scoped.url).toContain("/runs/run-1/");
    act(() => scoped.triggerOpen());

    // The unscoped socket's close event lands LATE — after the scoped
    // socket is already live. This must not wipe the live reference.
    act(() => unscoped.triggerClose());

    act(() => result.current.sendDecisionEdit("row-1", "answer"));

    expect(scoped.sent).toHaveLength(1);
    expect(JSON.parse(scoped.sent[0])).toMatchObject({
      type: "decision.edit",
      row_id: "row-1",
      new_answer: "answer",
    });
  });

  it("queues sends made before the socket opens and flushes them on open", () => {
    const { result } = renderHook(() =>
      useOppSocket({ slug: "my-opp", runId: "run-1" }),
    );
    const ws = MockWebSocket.instances[0];
    // Socket still CONNECTING — a raw send() would throw InvalidStateError.
    act(() => result.current.sendDecisionEdit("row-1", "early answer"));
    expect(ws.sent).toHaveLength(0);

    act(() => ws.triggerOpen());

    expect(ws.sent).toHaveLength(1);
    expect(JSON.parse(ws.sent[0])).toMatchObject({
      type: "decision.edit",
      row_id: "row-1",
      new_answer: "early answer",
    });
  });

  it("flushes queued sends on the replacement socket after a reconnect", () => {
    const { result, rerender } = renderHook(
      ({ runId }: { runId?: string }) => useOppSocket({ slug: "my-opp", runId }),
      { initialProps: { runId: undefined as string | undefined } },
    );
    act(() => MockWebSocket.instances[0].triggerOpen());

    // Edit staged in the gap: unscoped socket already closed by the runId
    // change, run-scoped socket not open yet.
    rerender({ runId: "run-1" });
    act(() => MockWebSocket.instances[0].triggerClose());
    act(() => result.current.sendDecisionEdit("row-1", "gap answer"));

    const scoped = MockWebSocket.instances[1];
    act(() => scoped.triggerOpen());

    expect(scoped.sent).toHaveLength(1);
    expect(JSON.parse(scoped.sent[0])).toMatchObject({
      row_id: "row-1",
      new_answer: "gap answer",
    });
  });

  it("routes decision.edited events to the handler", () => {
    const onDecisionEdited = vi.fn();
    renderHook(() =>
      useOppSocket({ slug: "my-opp", runId: "run-1", onDecisionEdited }),
    );
    const ws = MockWebSocket.instances[0];
    act(() => ws.triggerOpen());

    act(() =>
      ws.onmessage?.({
        data: JSON.stringify({
          event: "decision.edited",
          data: { row_id: "row-1", new_answer: "x", editor_email: "a@b.c", editor_name: "A" },
        }),
      }),
    );

    expect(onDecisionEdited).toHaveBeenCalledWith(
      expect.objectContaining({ row_id: "row-1", new_answer: "x" }),
    );
  });
});
