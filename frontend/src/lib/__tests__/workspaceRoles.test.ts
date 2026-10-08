import { describe, expect, it } from "vitest";

import {
  MINIMUM_ROLE,
  ROLE_DESCRIPTIONS,
  ROLE_LABELS,
  WORKSPACE_ROLES,
  assignableRoles,
  mayManage,
  roleAllows,
} from "@/lib/workspaceRoles";

describe("workspace roles (canopy-web's ACL)", () => {
  it("lists the four roles highest first, with their labels", () => {
    expect(WORKSPACE_ROLES).toEqual(["owner", "admin", "editor", "viewer"]);
    expect(WORKSPACE_ROLES.map((r) => ROLE_LABELS[r])).toEqual([
      "Owner",
      "Admin",
      "Editor",
      "Viewer",
    ]);
  });

  it("describes a viewer as view-only and an editor as able to work decisions", () => {
    expect(ROLE_DESCRIPTIONS.viewer).toBe("Can view.");
    expect(ROLE_DESCRIPTIONS.editor).toBe("Can confirm, change and comment on decisions.");
  });

  it("mirrors the backend's capability table", () => {
    expect(MINIMUM_ROLE).toEqual({
      read: "viewer",
      "content.write": "editor",
      "decisions.write": "editor",
      "summary.team_view": "admin",
      "logs.read": "admin",
      "members.manage": "admin",
      own: "owner",
    });
    expect(roleAllows("viewer", "decisions.write")).toBe(false);
    expect(roleAllows("editor", "decisions.write")).toBe(true);
    expect(roleAllows("editor", "summary.team_view")).toBe(false);
    expect(roleAllows("admin", "summary.team_view")).toBe(true);
    expect(roleAllows("admin", "own")).toBe(false);
    expect(roleAllows(null, "read")).toBe(false);
  });

  it("lets an admin grant only below itself; an owner grants anything", () => {
    expect(assignableRoles("owner")).toEqual(["owner", "admin", "editor", "viewer"]);
    expect(assignableRoles("admin")).toEqual(["editor", "viewer"]);
    expect(assignableRoles("editor")).toEqual([]);
    expect(assignableRoles("viewer")).toEqual([]);
    expect(mayManage("admin", "admin")).toBe(false);
    expect(mayManage("admin", "editor")).toBe(true);
    expect(mayManage("owner", "owner")).toBe(true);
  });
});
