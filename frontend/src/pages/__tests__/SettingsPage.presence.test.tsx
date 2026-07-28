import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as authApi from "@/api/auth";
import * as presenceApi from "@/api/presence";
import * as tokensApi from "@/api/tokens";
import { PRESENCE_PREFERENCE_CHANGED_EVENT } from "@/presence/events";
import { usePresenceReconnectNonce } from "@/presence/usePresenceReconnectNonce";
import SettingsPage from "@/pages/SettingsPage";

// SettingsPage fires listTokens/cliAuthStatus/novaAuthStatus on mount
// regardless of what this test cares about — stub them all so the toggle
// itself is what's under test.
function stubUnrelatedSettingsCalls() {
  vi.spyOn(tokensApi, "listTokens").mockResolvedValue([]);
  vi.spyOn(authApi, "cliAuthStatus").mockRejectedValue(new Error("not configured"));
  vi.spyOn(authApi, "novaAuthStatus").mockRejectedValue(new Error("not configured"));
}

function renderSettings() {
  return render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  );
}

describe("SettingsPage presence toggle", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    stubUnrelatedSettingsCalls();
  });

  afterEach(cleanup);

  it("loads the saved preference and reflects it in the checkbox", async () => {
    vi.spyOn(presenceApi, "getPresencePreference").mockResolvedValue({ show_presence: false });

    renderSettings();

    const checkbox = await screen.findByRole("checkbox", { name: /show me as viewing/i });
    expect((checkbox as HTMLInputElement).checked).toBe(false);
  });

  it("PATCHes on toggle and fires the reconnect signal that TopNav's badge is keyed on", async () => {
    vi.spyOn(presenceApi, "getPresencePreference").mockResolvedValue({ show_presence: true });
    const setPreference = vi
      .spyOn(presenceApi, "setPresencePreference")
      .mockResolvedValue({ show_presence: false });

    // Stand-in for TopNav's remount key — this is the SAME hook TopNav uses
    // (`<PresenceHeaderBadge key={presenceReconnectNonce} />`), rendered
    // independently so this test doesn't need to mount the whole nav
    // (workspace/router context) to observe it.
    const nonce = renderHook(() => usePresenceReconnectNonce());
    expect(nonce.result.current).toBe(0);

    renderSettings();
    const checkbox = await screen.findByRole("checkbox", { name: /show me as viewing/i });
    expect((checkbox as HTMLInputElement).checked).toBe(true);

    await act(async () => {
      fireEvent.click(checkbox);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(setPreference).toHaveBeenCalledWith(false);
    expect((checkbox as HTMLInputElement).checked).toBe(false);
    expect(nonce.result.current).toBe(1);
  });

  it("reverts the checkbox and does not fire the signal if the PATCH fails", async () => {
    vi.spyOn(presenceApi, "getPresencePreference").mockResolvedValue({ show_presence: true });
    vi.spyOn(presenceApi, "setPresencePreference").mockRejectedValue(new Error("network error"));

    const handler = vi.fn();
    window.addEventListener(PRESENCE_PREFERENCE_CHANGED_EVENT, handler);

    renderSettings();
    const checkbox = await screen.findByRole("checkbox", { name: /show me as viewing/i });

    await act(async () => {
      fireEvent.click(checkbox);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(handler).not.toHaveBeenCalled();
    expect((checkbox as HTMLInputElement).checked).toBe(true); // reverted

    window.removeEventListener(PRESENCE_PREFERENCE_CHANGED_EVENT, handler);
  });
});
