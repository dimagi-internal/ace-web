import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as slackApi from "@/api/slack";
import * as wsApi from "@/api/workspaces";
import type { WorkspaceDetail, WorkspaceMember, WorkspaceRole } from "@/api/workspaces";
import WorkspaceSettingsPage from "@/pages/WorkspaceSettingsPage";

function member(id: number, email: string, role: WorkspaceRole): WorkspaceMember {
  return {
    id,
    user: { id, email, display_name: email },
    role,
    joined_at: "2026-10-01T00:00:00Z",
  } as WorkspaceMember;
}

const MEMBERS = [
  member(1, "owner@x.org", "owner"),
  member(2, "admin@x.org", "admin"),
  member(3, "editor@x.org", "editor"),
  member(4, "viewer@x.org", "viewer"),
];

function renderAs(role: WorkspaceRole) {
  vi.spyOn(wsApi, "getWorkspace").mockResolvedValue({
    slug: "spark",
    name: "Spark",
    drive_root_folder_id: "f",
    role,
    member_count: 4,
    auto_join_domains: [],
    default_tenancy: {},
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
  } as WorkspaceDetail);
  vi.spyOn(wsApi, "listMembers").mockResolvedValue(MEMBERS);
  vi.spyOn(wsApi, "getDriveConfig").mockResolvedValue({ service_account_email: "sa@x" });
  vi.spyOn(wsApi, "verifyDriveAccess").mockResolvedValue({
    ok: true,
    sample_files: [],
    total_visible: 0,
  });
  vi.spyOn(wsApi, "listActivity").mockResolvedValue([]);
  const invites = vi.spyOn(wsApi, "listPendingInvites").mockResolvedValue([
    {
      email: "anne@sparkmicrogrants.org",
      role: "editor",
      invited_by_email: "ace@dimagi-ai.com",
      created_at: "2026-10-01T00:00:00Z",
      expires_at: "2026-10-15T00:00:00Z",
    },
  ]);
  vi.spyOn(slackApi, "getSlackStatus").mockRejectedValue(new Error("no slack"));
  render(
    <MemoryRouter initialEntries={["/w/spark/settings"]}>
      <Routes>
        <Route path="/w/:workspaceSlug/settings" element={<WorkspaceSettingsPage />} />
      </Routes>
    </MemoryRouter>,
  );
  return { invites };
}

function optionLabels(select: HTMLElement) {
  return within(select)
    .getAllByRole("option")
    .filter((o) => !(o as HTMLOptionElement).disabled)
    .map((o) => o.textContent);
}

describe("WorkspaceSettingsPage roles", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(cleanup);

  it("offers an owner all four roles, labelled, in the invite picker", async () => {
    renderAs("owner");
    const picker = await screen.findByLabelText("Role for the invite");
    expect(optionLabels(picker)).toEqual(["Owner", "Admin", "Editor", "Viewer"]);
    expect(screen.getByTestId("invite-role-description").textContent).toBe(
      "Editor: Can confirm, change and comment on decisions.",
    );
  });

  it("offers an admin only Editor and Viewer, and no picker on owners or admins", async () => {
    renderAs("admin");
    const picker = await screen.findByLabelText("Role for the invite");
    expect(optionLabels(picker)).toEqual(["Editor", "Viewer"]);
    expect(screen.queryByLabelText("Role for owner@x.org")).toBeNull();
    expect(screen.queryByLabelText("Role for admin@x.org")).toBeNull();
    const editorRow = screen.getByLabelText("Role for editor@x.org");
    expect(optionLabels(editorRow)).toEqual(["Editor", "Viewer"]);
    expect(await screen.findByText("anne@sparkmicrogrants.org")).toBeTruthy();
  });

  it("shows an editor the roles as labels, with no invite or member controls", async () => {
    const { invites } = renderAs("editor");
    expect((await screen.findAllByText("viewer@x.org")).length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("Role for the invite")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.getByText("Viewer").getAttribute("title")).toBe("Can view.");
    expect(screen.getByText("Admin")).toBeTruthy();
    expect(invites).not.toHaveBeenCalled();
  });
});
