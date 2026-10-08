import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api/siteAdmin";
import type { SiteAdminUser, SiteAdminUsers } from "@/api/siteAdmin";
import SiteAdminUsersPage from "@/pages/SiteAdminUsersPage";

function user(id: number, email: string, is_staff: boolean): SiteAdminUser {
  return {
    id,
    email,
    display_name: email.split("@")[0],
    is_staff,
    is_active: true,
    created_at: "2026-10-01T00:00:00Z",
    last_login: null,
    workspaces: [{ workspace_slug: "spark", workspace_name: "Spark", role: "editor" }],
  } as SiteAdminUser;
}

const DATA: SiteAdminUsers = {
  users: [user(1, "boss@x.org", true), user(17, "ada@dimagi-ai.com", false)],
  recent_changes: [],
} as SiteAdminUsers;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("SiteAdminUsersPage", () => {
  it("lists users with workspace roles", async () => {
    vi.spyOn(api, "listSiteAdminUsers").mockResolvedValue(DATA);
    render(<SiteAdminUsersPage />);
    expect(await screen.findByText("ada@dimagi-ai.com")).toBeTruthy();
    expect(screen.getAllByText("Spark (editor)").length).toBe(2);
  });

  it("names the person in the confirm step and only then grants", async () => {
    vi.spyOn(api, "listSiteAdminUsers").mockResolvedValue(DATA);
    const set = vi.spyOn(api, "setUserStaff").mockResolvedValue(user(17, "ada@dimagi-ai.com", true));
    render(<SiteAdminUsersPage />);
    fireEvent.click(await screen.findByLabelText("Make admin ada@dimagi-ai.com"));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.textContent).toContain("ada@dimagi-ai.com");
    expect(set).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Make admin" }));
    await waitFor(() => expect(set).toHaveBeenCalledWith(17, true));
  });

  it("cancel makes no change", async () => {
    vi.spyOn(api, "listSiteAdminUsers").mockResolvedValue(DATA);
    const set = vi.spyOn(api, "setUserStaff");
    render(<SiteAdminUsersPage />);
    fireEvent.click(await screen.findByLabelText("Remove admin from boss@x.org"));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(set).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("shows the server's guard message on a 409", async () => {
    vi.spyOn(api, "listSiteAdminUsers").mockResolvedValue(DATA);
    vi.spyOn(api, "setUserStaff").mockRejectedValue(
      new Error("You can't remove your own site admin. Ask another site admin to do it."),
    );
    render(<SiteAdminUsersPage />);
    fireEvent.click(await screen.findByLabelText("Remove admin from boss@x.org"));
    fireEvent.click(screen.getByRole("button", { name: "Remove admin" }));
    expect((await screen.findByRole("alert")).textContent).toContain("your own site admin");
  });

  it("renders not-found, not a permissions page, when the API 404s", async () => {
    vi.spyOn(api, "listSiteAdminUsers").mockRejectedValue(new Error("Not found"));
    render(<SiteAdminUsersPage />);
    expect(await screen.findByText("Page not found")).toBeTruthy();
  });
});
