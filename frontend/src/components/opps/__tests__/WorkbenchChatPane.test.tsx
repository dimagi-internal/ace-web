import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import * as canopyApi from "@/canopy/api";
import { useCanopyStatus } from "@/canopy/useCanopyStatus";
import { WorkbenchChatPane } from "@/components/opps/WorkbenchChatPane";

vi.mock("@/canopy/CanopyChatPanel", () => ({
  CanopyChatPanel: ({ sessionId }: { sessionId: string }) => (
    <div data-testid="canopy-chat-panel-stub">{sessionId}</div>
  ),
}));

vi.mock("@/canopy/useCanopyStatus", () => ({
  useCanopyStatus: vi.fn(),
}));

const useCanopyStatusMock = vi.mocked(useCanopyStatus);

describe("WorkbenchChatPane — canopy is unreachable/disabled", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a degrade-visibly message instead of a dead legacy UI when status hasn't loaded / is off", () => {
    useCanopyStatusMock.mockReturnValue(null);
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
    expect(screen.getByText(/canopy chat is unreachable/i)).toBeInTheDocument();
  });
});

describe("WorkbenchChatPane — canopy hosted chat", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useCanopyStatusMock.mockReturnValue({
      enabled: true,
      base_url: "/canopy",
      workspace: "ws-1",
      agent: "echo",
    });
  });

  it("'Start a chat about this step' creates a canopy session and renders it inline", async () => {
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
      expect(createSpy).toHaveBeenCalledWith("ws-1", {
        title: "idea-to-pdd",
        opp_slug: "opp-a",
        opp_run_id: "run-001",
        opp_step_skill: "idea-to-pdd",
      }),
    );
    const panel = await screen.findByTestId("canopy-chat-panel-stub");
    expect(panel).toHaveTextContent("canopy-new");
  });

  it("scopes the linked-chats list to this ace workspace via origin_key (C1)", async () => {
    vi.spyOn(canopyApi, "listCanopySessions").mockResolvedValue([]);

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

    await waitFor(() =>
      expect(canopyApi.listCanopySessions).toHaveBeenCalledWith(
        "/canopy",
        expect.objectContaining({ origin_key: "ace-web:ws-1" }),
      ),
    );
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
