/**
 * Workspace roles — canopy-web's ACL (owner > admin > editor > viewer).
 *
 * The SERVER decides every permission (`apps/workspaces/permissions.py`,
 * `MINIMUM_ROLE`); this module only decides what the UI OFFERS, mirroring
 * that table so a control is never drawn for an action the server will 403.
 * Keep the two in step: a capability's minimum role here must equal the
 * backend's.
 */
import type { WorkspaceRole } from "@/api/workspaces";

/** Highest first — the order role pickers list them in. */
export const WORKSPACE_ROLES: readonly WorkspaceRole[] = ["owner", "admin", "editor", "viewer"];

const RANK: Record<WorkspaceRole, number> = { viewer: 0, editor: 1, admin: 2, owner: 3 };

export const ROLE_LABELS: Record<WorkspaceRole, string> = {
  owner: "Owner",
  admin: "Admin",
  editor: "Editor",
  viewer: "Viewer",
};

/** One line per role, as a person choosing a role needs to read it. */
export const ROLE_DESCRIPTIONS: Record<WorkspaceRole, string> = {
  owner: "Holds the keys: workspace settings, Drive folder, tenancy, and everything below.",
  admin: "Runs the workspace: invites and manages editors and viewers, sees the team view and audit log.",
  editor: "Can confirm, change and comment on decisions.",
  viewer: "Can view.",
};

/** Capability → minimum role. Mirrors `permissions.MINIMUM_ROLE`. */
export const MINIMUM_ROLE = {
  read: "viewer",
  "content.write": "editor",
  "decisions.write": "editor",
  "summary.team_view": "admin",
  "logs.read": "admin",
  "members.manage": "admin",
  own: "owner",
} as const satisfies Record<string, WorkspaceRole>;

export type Capability = keyof typeof MINIMUM_ROLE;

export function roleAllows(role: WorkspaceRole | null | undefined, capability: Capability): boolean {
  if (!role) return false;
  return RANK[role] >= RANK[MINIMUM_ROLE[capability]];
}

/**
 * May `actor` act on a member holding `target` (change or remove them), or
 * invite at `target`? An owner acts on anyone; an admin only strictly below
 * itself. Mirrors `permissions.may_manage_member`.
 */
export function mayManage(actor: WorkspaceRole | null | undefined, target: WorkspaceRole): boolean {
  if (actor === "owner") return true;
  if (!roleAllows(actor, "members.manage")) return false;
  return RANK[target] < RANK[actor!];
}

/** The roles `actor` may grant — the options of an invite or role picker. */
export function assignableRoles(actor: WorkspaceRole | null | undefined): WorkspaceRole[] {
  return WORKSPACE_ROLES.filter((r) => mayManage(actor, r));
}
