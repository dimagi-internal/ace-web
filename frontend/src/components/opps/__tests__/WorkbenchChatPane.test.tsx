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
    // The pane declares its page state as soon as a chat is open (see the
    // "telling the agent what is on screen" block below). Stubbed here so the
    // tests in THIS block, which are about something else, don't reach for a
    // delegated token and log a caught failure over every run's output.
    vi.spyOn(canopyApi, "declareCanopyPageState").mockResolvedValue(undefined);
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

describe("WorkbenchChatPane — telling the agent what is on screen", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useCanopyStatusMock.mockReturnValue({
      enabled: true,
      base_url: "/canopy",
      workspace: "ws-1",
      agent: "echo",
    });
  });

  function renderPane(skill: string, runId = "run-001") {
    return render(
      <MemoryRouter initialEntries={["/w/ws-1/opps/opp-a"]}>
        <Routes>
          <Route
            path="/w/:workspaceSlug/opps/:slug"
            element={
              <WorkbenchChatPane
                slug="opp-a"
                runId={runId}
                skill={skill}
                skillDisplayName="Idea to PDD"
              />
            }
          />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("declares the live selection against the open chat", async () => {
    vi.spyOn(canopyApi, "listCanopySessions").mockResolvedValue([
      {
        id: "canopy-1",
        title: "About this step",
        agent_slug: "echo",
        updated_at: "2026-09-16T00:00:00Z",
      },
    ]);
    const declare = vi
      .spyOn(canopyApi, "declareCanopyPageState")
      .mockResolvedValue(undefined);

    renderPane("idea-to-pdd");

    await waitFor(() => expect(declare).toHaveBeenCalled());
    const [base, sessionId, state] = declare.mock.calls[0];
    expect(base).toBe("/canopy");
    expect(sessionId).toBe("canopy-1");
    expect(state.resource).toBe("opp://opp-a/run-001");
    expect(state.filters).toMatchObject({ step_skill: "idea-to-pdd", run_id: "run-001" });
  });

  it("names a backing tool that actually exists on ace-web's MCP surface", async () => {
    // `backing_tool` is a promise to the agent: call THIS to read the rows I am
    // showing. A name that resolves to nothing is worse than sending none,
    // because the agent will try it. This is the operationId FastMCP derives
    // for GET /api/w/{ws}/opps/{slug}/steps/{skill} — the Workbench's own read.
    vi.spyOn(canopyApi, "listCanopySessions").mockResolvedValue([
      {
        id: "canopy-1",
        title: "t",
        agent_slug: "echo",
        updated_at: "2026-09-16T00:00:00Z",
      },
    ]);
    const declare = vi
      .spyOn(canopyApi, "declareCanopyPageState")
      .mockResolvedValue(undefined);

    renderPane("idea-to-pdd");

    await waitFor(() => expect(declare).toHaveBeenCalled());
    expect(declare.mock.calls[0][2].backing_tool).toBe("apps_opps_api_get_step");
  });

  it("declares nothing while no chat is open", async () => {
    // There is no session to attach a page to, and an empty declaration is a
    // legitimate state — the agent simply starts without one.
    vi.spyOn(canopyApi, "listCanopySessions").mockResolvedValue([]);
    const declare = vi
      .spyOn(canopyApi, "declareCanopyPageState")
      .mockResolvedValue(undefined);

    renderPane("idea-to-pdd");

    await screen.findByRole("button", { name: /start a chat about this step/i });
    expect(declare).not.toHaveBeenCalled();
  });

  it("re-declares when the reader moves to another step", async () => {
    // The whole point: session metadata is frozen at create, so without this
    // the agent keeps answering about the step the chat was opened on.
    vi.spyOn(canopyApi, "listCanopySessions").mockResolvedValue([
      {
        id: "canopy-1",
        title: "t",
        agent_slug: "echo",
        updated_at: "2026-09-16T00:00:00Z",
      },
    ]);
    const declare = vi
      .spyOn(canopyApi, "declareCanopyPageState")
      .mockResolvedValue(undefined);

    const { rerender } = renderPane("idea-to-pdd");
    await waitFor(() => expect(declare).toHaveBeenCalledTimes(1));

    rerender(
      <MemoryRouter initialEntries={["/w/ws-1/opps/opp-a"]}>
        <Routes>
          <Route
            path="/w/:workspaceSlug/opps/:slug"
            element={
              <WorkbenchChatPane
                slug="opp-a"
                runId="run-001"
                skill="connect-setup"
                skillDisplayName="Connect setup"
              />
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(declare).toHaveBeenCalledTimes(2));
    expect(declare.mock.calls[1][2].filters).toMatchObject({
      step_skill: "connect-setup",
    });
  });

  it("keeps the chat usable when canopy refuses the declaration", async () => {
    // A page-state PUT is an enhancement. If it fails the agent knows less —
    // the conversation itself must not break.
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(canopyApi, "listCanopySessions").mockResolvedValue([
      {
        id: "canopy-1",
        title: "About this step",
        agent_slug: "echo",
        updated_at: "2026-09-16T00:00:00Z",
      },
    ]);
    vi.spyOn(canopyApi, "declareCanopyPageState").mockRejectedValue(
      new Error("canopy is down"),
    );

    renderPane("idea-to-pdd");

    expect(await screen.findByTestId("canopy-chat-panel-stub")).toHaveTextContent(
      "canopy-1",
    );
  });
});
