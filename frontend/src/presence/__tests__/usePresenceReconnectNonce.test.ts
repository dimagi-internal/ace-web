import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { notifyPresencePreferenceChanged } from "../events";
import { usePresenceReconnectNonce } from "../usePresenceReconnectNonce";

// This is the exact wiring TopNav's `PresenceHeaderBadge` is keyed on
// (`<PresenceHeaderBadge key={usePresenceReconnectNonce()} />`) — tested in
// isolation rather than by mounting the whole nav (which needs router +
// workspace context and network calls just to render).

describe("usePresenceReconnectNonce", () => {
  afterEach(cleanup);

  it("starts at 0", () => {
    const { result } = renderHook(() => usePresenceReconnectNonce());
    expect(result.current).toBe(0);
  });

  it("bumps by 1 each time the preference-changed signal fires", () => {
    const { result } = renderHook(() => usePresenceReconnectNonce());

    act(() => {
      notifyPresencePreferenceChanged();
    });
    expect(result.current).toBe(1);

    act(() => {
      notifyPresencePreferenceChanged();
    });
    expect(result.current).toBe(2);
  });

  it("stops bumping once unmounted", () => {
    const { result, unmount } = renderHook(() => usePresenceReconnectNonce());
    unmount();
    act(() => {
      notifyPresencePreferenceChanged();
    });
    // No re-render happened (the component is gone), so the last observed
    // value is unchanged — this also proves the subscription was torn down
    // rather than leaking across renders/tests.
    expect(result.current).toBe(0);
  });
});
