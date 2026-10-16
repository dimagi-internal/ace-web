import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as wsApi from "@/api/workspaces";
import type { MyPendingInvite, WorkspaceSummary } from "@/api/workspaces";
import { ErrorState } from "@/components/opps/LoadingStates";

import { WorkspaceAccessGate } from "./WorkspaceAccessGate";

function workspace(slug: string): WorkspaceSummary {
  return {
    slug,
    name: slug,
    drive_root_folder_id: "f",
    role: "editor",
    member_count: 1,
    default_tenancy: {},
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
  } as WorkspaceSummary;
}

const INVITE: MyPendingInvite = {
  workspace_slug: "spark",
  workspace_display_name: "Spark Microgrants",
  role: "editor",
  invited_by_email: "owner@example.com",
  expires_at: "2026-10-30T00:00:00Z",
  accept_url: "/invite/tok123",
};

// A workspace page whose load 404'd — what OppRunPage renders on a real
// not-found inside a workspace the visitor belongs to.
function NotFoundPage() {
  return <ErrorState message="404 Not found" />;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/w/:workspaceSlug" element={<WorkspaceAccessGate />}>
          <Route path="opps/:slug" element={<NotFoundPage />} />
        </Route>
        <Route path="/invite/:token" element={<div>invite page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("WorkspaceAccessGate", () => {
  it("offers a non-member their pending invite for this workspace", async () => {
    vi.spyOn(wsApi, "listWorkspaces").mockResolvedValue([workspace("other")]);
    const mine = vi.spyOn(wsApi, "listMyPendingInvites").mockResolvedValue([INVITE]);

    renderAt("/w/spark/opps/bednet");

    expect(
      await screen.findByText("You've been invited to Spark Microgrants as an editor."),
    ).toBeTruthy();
    const accept = screen.getByRole("link", { name: "Accept invitation" });
    expect(accept.getAttribute("href")).toBe("/invite/tok123");
    expect(mine).toHaveBeenCalledWith("spark");
    expect(screen.queryByText(/doesn't exist \(anymore\)/)).toBeNull();
  });

  it("tells a non-member with no invite to ask for one", async () => {
    vi.spyOn(wsApi, "listWorkspaces").mockResolvedValue([workspace("other")]);
    vi.spyOn(wsApi, "listMyPendingInvites").mockResolvedValue([]);

    renderAt("/w/spark/opps/bednet");

    expect(await screen.findByText("You don't have access to this workspace")).toBeTruthy();
    expect(
      screen.getByText("Ask the person who sent you this link to invite you."),
    ).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Accept invitation" })).toBeNull();
    expect(screen.queryByText(/moved in Drive/)).toBeNull();
  });

  it("ignores an invite for a different workspace", async () => {
    vi.spyOn(wsApi, "listWorkspaces").mockResolvedValue([]);
    vi.spyOn(wsApi, "listMyPendingInvites").mockResolvedValue([
      { ...INVITE, workspace_slug: "kmc" },
    ]);

    renderAt("/w/spark/opps/bednet");

    expect(await screen.findByText("You don't have access to this workspace")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Accept invitation" })).toBeNull();
  });

  it("falls back to the plain no-access copy when invites can't be read", async () => {
    vi.spyOn(wsApi, "listWorkspaces").mockResolvedValue([]);
    vi.spyOn(wsApi, "listMyPendingInvites").mockRejectedValue(new Error("boom"));

    renderAt("/w/spark/opps/bednet");

    expect(await screen.findByText("You don't have access to this workspace")).toBeTruthy();
  });

  it("leaves a member's not-found copy unchanged", async () => {
    vi.spyOn(wsApi, "listWorkspaces").mockResolvedValue([workspace("spark")]);
    const mine = vi.spyOn(wsApi, "listMyPendingInvites");

    renderAt("/w/spark/opps/bednet");

    expect(
      await screen.findByText(
        "This doesn't exist (anymore). It may have been deleted, renamed, or moved in Drive.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("You don't have access to this workspace")).toBeNull();
    expect(mine).not.toHaveBeenCalled();
  });
});
