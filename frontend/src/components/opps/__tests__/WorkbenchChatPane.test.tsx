import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import * as oppsApi from "@/api/opps";
import type { LinkedChat } from "@/api/types.ws";
import * as canopyApi from "@/canopy/api";
import { useCanopyStatus } from "@/canopy/useCanopyStatus";
import { WorkbenchChatPane, deriveLegacySelection } from "@/components/opps/WorkbenchChatPane";

// The ChatPanel pulls in WebSocket hooks and getSession; we don't need
// to exercise any of that — stub it out so the "no chats yet" empty
// state is the only render path we care about.
vi.mock("@/components/opps/ChatPanel", () => ({
  ChatPanel: () => <div data-testid="chat-panel-stub" />,
}));

vi.mock("@/canopy/CanopyChatPanel", () => ({
  CanopyChatPanel: ({ sessionId }: { sessionId: string }) => (
    <div data-testid="canopy-chat-panel-stub">{sessionId}</div>
  ),
}));

vi.mock("@/canopy/useCanopyStatus", () => ({
  useCanopyStatus: vi.fn(),
}));

const useCanopyStatusMock = vi.mocked(useCanopyStatus);

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{loc.pathname}</div>;
}

function stepChat(slug: string): LinkedChat {
  return {
    slug,
    title: slug,
    updated_at: "",
    owner_email: "",
    source: "web",
    kind: "step",
    step_skill: null,
    step_skill_display: null,
    preview: "",
  };
}

describe("deriveLegacySelection (fix-round-1 review, Minor 5)", () => {
  const list = [stepChat("keep-me")];

  it("drops a stale legacy selection no longer present in the refreshed list, falling through to the first step chat", () => {
    expect(deriveLegacySelection({ kind: "legacy", slug: "gone" }, list)).toEqual({
      kind: "legacy",
      slug: "keep-me",
    });
  });

  it("keeps a legacy selection that's still present in the list", () => {
    const prev = { kind: "legacy" as const, slug: "keep-me" };
    expect(deriveLegacySelection(prev, list)).toEqual(prev);
  });

  it("never touches a canopy selection — a legacy-scoped refresh can't see canopy sessions at all", () => {
    const prev = { kind: "canopy" as const, id: "canopy-1" };
    expect(deriveLegacySelection(prev, list)).toBe(prev);
  });

  it("falls through to null when nothing matches and there's no step chat", () => {
    expect(deriveLegacySelection(null, [])).toBeNull();
    expect(deriveLegacySelection({ kind: "legacy", slug: "gone" }, [])).toBeNull();
  });
});

describe("WorkbenchChatPane — start-chat navigation (issue #470)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // No chats yet → component renders the "Start a chat" empty-state CTA.
    vi.spyOn(oppsApi, "getLinkedChats").mockResolvedValue([]);
    // Canopy hosted chat OFF for every pre-existing test in this describe
    // block — the flag must be a true no-op on the legacy discuss-step flow.
    useCanopyStatusMock.mockReturnValue(null);
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

describe("WorkbenchChatPane — canopy hosted chat (flag ON)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(oppsApi, "getLinkedChats").mockResolvedValue([]);
    useCanopyStatusMock.mockReturnValue({
      enabled: true,
      base_url: "/canopy",
      workspace: "ws-1",
      agent: "echo",
    });
  });

  it("'Discuss this step' creates a canopy session and renders it inline", async () => {
    vi.spyOn(canopyApi, "listCanopySessions").mockResolvedValue([]);
    const createSpy = vi
      .spyOn(canopyApi, "createCanopySession")
      .mockResolvedValue({ id: "canopy-new" });

    render(
      <MemoryRouter initialEntries={["/w/ws-1/opps/opp-a"]}>
        <Routes>
          <Route
            path="/w/:workspaceSlug/opps/:slug"
            element={<WorkbenchChatPane slug="opp-a" runId="run-001" skill="idea-to-pdd" />}
          />
        </Routes>
      </MemoryRouter>,
    );

    const btn = await screen.findByRole("button", { name: /start a chat about this step/i });
    fireEvent.click(btn);

    await waitFor(() =>
      expect(createSpy).toHaveBeenCalledWith({
        title: "idea-to-pdd",
        opp_slug: "opp-a",
        opp_run_id: "run-001",
        opp_step_skill: "idea-to-pdd",
      }),
    );
    const panel = await screen.findByTestId("canopy-chat-panel-stub");
    expect(panel).toHaveTextContent("canopy-new");
  });

  it("lists this run's canopy chats and selecting one renders it inline", async () => {
    vi.spyOn(canopyApi, "listCanopySessions").mockResolvedValue([
      { id: "canopy-1", title: "First chat", agent_slug: "echo", updated_at: "now" },
      { id: "canopy-2", title: "Second chat", agent_slug: "echo", updated_at: "now" },
    ]);

    render(
      <MemoryRouter initialEntries={["/w/ws-1/opps/opp-a"]}>
        <Routes>
          <Route
            path="/w/:workspaceSlug/opps/:slug"
            element={<WorkbenchChatPane slug="opp-a" runId="run-001" skill="idea-to-pdd" />}
          />
        </Routes>
      </MemoryRouter>,
    );

    // Auto-selects the first canopy chat.
    const panel = await screen.findByTestId("canopy-chat-panel-stub");
    expect(panel).toHaveTextContent("canopy-1");

    fireEvent.click(screen.getByRole("button", { name: /second chat/i }));
    await waitFor(() =>
      expect(screen.getByTestId("canopy-chat-panel-stub")).toHaveTextContent("canopy-2"),
    );
  });
});
