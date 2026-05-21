import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import * as oppsApi from "@/api/opps";
import { WorkbenchChatPane } from "@/components/opps/WorkbenchChatPane";

// The ChatPanel pulls in WebSocket hooks and getSession; we don't need
// to exercise any of that — stub it out so the "no chats yet" empty
// state is the only render path we care about.
vi.mock("@/components/opps/ChatPanel", () => ({
  ChatPanel: () => <div data-testid="chat-panel-stub" />,
}));

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{loc.pathname}</div>;
}

describe("WorkbenchChatPane — start-chat navigation (issue #470)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // No chats yet → component renders the "Start a chat" empty-state CTA.
    vi.spyOn(oppsApi, "getLinkedChats").mockResolvedValue([]);
  });

  it("navigates to the new session on 201 instead of leaving the button stuck on Starting…", async () => {
    vi.spyOn(oppsApi, "discussStep").mockResolvedValue({
      session_slug: "fresh-session-xyz",
    } as unknown as Awaited<ReturnType<typeof oppsApi.discussStep>>);

    render(
      <MemoryRouter initialEntries={["/w/ws-1/opps/opp-a"]}>
        <Routes>
          <Route
            path="/w/:workspaceSlug/opps/:slug"
            element={
              <>
                <WorkbenchChatPane slug="opp-a" runId="run-001" skill="idea-to-pdd" />
                <LocationProbe />
              </>
            }
          />
          <Route path="/w/:workspaceSlug/chat/:sessionSlug" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    const btn = await screen.findByRole("button", { name: /start a chat about this step/i });
    fireEvent.click(btn);

    // Lands on the new session URL.
    await waitFor(() =>
      expect(screen.getByTestId("location").textContent).toBe(
        "/w/ws-1/chat/fresh-session-xyz",
      ),
    );
  });

  it("resets the Starting… button on error so the user can retry", async () => {
    vi.spyOn(oppsApi, "discussStep").mockRejectedValue(new Error("boom"));

    render(
      <MemoryRouter initialEntries={["/w/ws-1/opps/opp-a"]}>
        <Routes>
          <Route
            path="/w/:workspaceSlug/opps/:slug"
            element={
              <WorkbenchChatPane slug="opp-a" runId="run-001" skill="idea-to-pdd" />
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    const btn = await screen.findByRole("button", { name: /start a chat about this step/i });
    fireEvent.click(btn);

    // Error surfaces; button is no longer disabled / stuck on Starting….
    await screen.findByRole("alert");
    const after = await screen.findByRole("button", { name: /start a chat about this step/i });
    expect(after).not.toBeDisabled();
  });
});
