import { waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  notifyPresencePreferenceChanged,
  PRESENCE_PREFERENCE_CHANGED_EVENT,
  subscribeToPresencePreferenceChanged,
} from "../events";

describe("notifyPresencePreferenceChanged", () => {
  it("dispatches the same-tab window event exactly once", () => {
    const handler = vi.fn();
    window.addEventListener(PRESENCE_PREFERENCE_CHANGED_EVENT, handler);
    notifyPresencePreferenceChanged();
    window.removeEventListener(PRESENCE_PREFERENCE_CHANGED_EVENT, handler);
    expect(handler).toHaveBeenCalledTimes(1);
  });
});

describe("subscribeToPresencePreferenceChanged", () => {
  afterEach(() => vi.restoreAllMocks());

  it("fires the callback on the same-tab signal", () => {
    const onChanged = vi.fn();
    const unsubscribe = subscribeToPresencePreferenceChanged(onChanged);
    notifyPresencePreferenceChanged();
    expect(onChanged).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("stops firing once unsubscribed", () => {
    const onChanged = vi.fn();
    const unsubscribe = subscribeToPresencePreferenceChanged(onChanged);
    unsubscribe();
    notifyPresencePreferenceChanged();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("also broadcasts cross-tab via BroadcastChannel when available", () => {
    // BroadcastChannel delivery is asynchronous even within the same
    // document (a message posted from one channel object is not visible on
    // another same-named channel object until a later task), so this only
    // asserts the channel is actually used — not synchronous delivery,
    // which would be a false requirement.
    const postMessage = vi.fn();
    const close = vi.fn();
    const OriginalBC = globalThis.BroadcastChannel;
    class FakeBroadcastChannel {
      name: string;
      onmessage: ((e: MessageEvent) => void) | null = null;
      constructor(name: string) {
        this.name = name;
      }
      postMessage = postMessage;
      close = close;
    }
    // @ts-expect-error -- test double, not the real BroadcastChannel shape
    globalThis.BroadcastChannel = FakeBroadcastChannel;

    notifyPresencePreferenceChanged();

    // The payload is a per-tab id (see events.ts), not a fixed literal —
    // just assert something was actually posted and the one-shot channel
    // was closed again.
    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage.mock.calls[0][0]).toBeTruthy();
    expect(close).toHaveBeenCalledTimes(1);

    globalThis.BroadcastChannel = OriginalBC;
  });

  it("fires for a broadcast from a DIFFERENT tab, asynchronously, without double-firing for its own broadcast", async () => {
    const onChanged = vi.fn();
    const unsubscribe = subscribeToPresencePreferenceChanged(onChanged);

    // This tab's own notify: the window event fires synchronously (call
    // #1); this tab's own BroadcastChannel echo (same TAB_ID), whenever it
    // eventually lands, must NOT produce a second call.
    notifyPresencePreferenceChanged();
    expect(onChanged).toHaveBeenCalledTimes(1);

    // A genuinely different tab never runs THIS module's `notify()` — real
    // browser tabs have entirely separate `window` globals, so re-importing
    // this module (which only resets the JS module cache, not `window`)
    // would not actually model that. Simulate a foreign tab directly at the
    // BroadcastChannel level instead: same channel name (this module's
    // private constant, deliberately duplicated here), a payload that is
    // NOT this tab's TAB_ID.
    const foreignTab = new BroadcastChannel("ace:presence-preference");
    foreignTab.postMessage("a-different-tabs-id");
    foreignTab.close();

    // BroadcastChannel delivery is a real task, not a microtask — wait for it.
    await waitFor(() => {
      expect(onChanged).toHaveBeenCalledTimes(2);
    });

    // And stays at 2 — the earlier same-tab echo never lands as a THIRD call.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(onChanged).toHaveBeenCalledTimes(2);

    unsubscribe();
  });

  it("falls back to same-tab-only when BroadcastChannel is unavailable", () => {
    const OriginalBC = globalThis.BroadcastChannel;
    // @ts-expect-error -- simulate an environment without BroadcastChannel
    delete globalThis.BroadcastChannel;

    const onChanged = vi.fn();
    const unsubscribe = subscribeToPresencePreferenceChanged(onChanged);
    expect(() => notifyPresencePreferenceChanged()).not.toThrow();
    expect(onChanged).toHaveBeenCalledTimes(1);
    unsubscribe();

    globalThis.BroadcastChannel = OriginalBC;
  });
});
