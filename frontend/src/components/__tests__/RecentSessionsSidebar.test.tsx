import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { RecentSessionsSidebar } from "../RecentSessionsSidebar";
import { useCanopyStatus } from "../../canopy/useCanopyStatus";
import * as canopyApi from "../../canopy/api";

/**
 * The sidebar's ace-web-native "Legacy" session list (grouped by opp,
 * issue #527's visual grouping) was retired with the rest of the
 * interactive chat UI in favor of canopy-hosted chat — see the PR that
 * deleted `useSessionSocket`/`sessionReducer`/local `ChatPanel`. This file
 * covers what's left: the canopy session list + New Chat.
 */

vi.mock("../../canopy/useCanopyStatus", () => ({
  useCanopyStatus: vi.fn(),
}));

const useCanopyStatusMock = vi.mocked(useCanopyStatus);

function renderSidebar() {
  return render(
    <MemoryRouter initialEntries={["/w/ws-1/host"]}>
      <Routes>
        <Route
          path="/w/:workspaceSlug/host"
          element={<RecentSessionsSidebar currentSlug={null} currentCanopyId="canopy-1" />}
        />
        <Route path="/w/:workspaceSlug/chat/c/:canopyId" element={<div data-testid="landed" />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RecentSessionsSidebar — canopy unreachable/disabled", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useCanopyStatusMock.mockReturnValue(null);
  });

  it("disables New Chat and shows an unreachable message rather than a dead legacy list", () => {
    renderSidebar();
    expect(screen.getByRole("button", { name: /new chat/i })).toBeDisabled();
    expect(screen.getByText(/unreachable/i)).toBeInTheDocument();
  });
});

describe("RecentSessionsSidebar — canopy hosted chat", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(canopyApi, "listCanopySessions").mockResolvedValue([
      {
        id: "canopy-1",
        title: "Canopy chat",
        agent_slug: "echo",
        updated_at: new Date().toISOString(),
      },
    ]);
    useCanopyStatusMock.mockReturnValue({
      enabled: true,
      base_url: "/canopy",
      workspace: "ws-1",
      agent: "echo",
    });
  });

  it("lists canopy sessions, highlighting the active one", async () => {
    renderSidebar();
    const row = await screen.findByText("Canopy chat");
    expect(row.closest("a")).toHaveClass("bg-accent");
  });

  it("scopes the canopy session list to this ace workspace via origin_key", async () => {
    renderSidebar();
    await waitFor(() =>
      expect(canopyApi.listCanopySessions).toHaveBeenCalledWith(
        "/canopy",
        expect.objectContaining({ origin_key: "ace-web:ws-1" }),
      ),
    );
  });

  it("New Chat creates a canopy session and navigates to the canopy route", async () => {
    const createSpy = vi
      .spyOn(canopyApi, "createCanopySession")
      .mockResolvedValue({ id: "canopy-new" });

    renderSidebar();
    await waitFor(() => expect(canopyApi.listCanopySessions).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /new chat/i }));

    await waitFor(() => expect(createSpy).toHaveBeenCalledWith("ws-1", {}));
    await screen.findByTestId("landed");
  });

  it("surfaces a visible error instead of silently doing nothing when createCanopySession fails", async () => {
    vi.spyOn(canopyApi, "createCanopySession").mockRejectedValue(
      new Error("Failed to create canopy session: 404"),
    );

    renderSidebar();
    await waitFor(() => expect(canopyApi.listCanopySessions).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /new chat/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/404/);
    expect(screen.queryByTestId("landed")).not.toBeInTheDocument();
  });
});
