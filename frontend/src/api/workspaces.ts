import { apiV2 } from "./client.v2";
import { apiFetch } from "./client";
import type { components } from "./generated";

// ---------------------------------------------------------------------------
// v2 canonical types — exported for consumer files
// ---------------------------------------------------------------------------

/** v2 WorkspaceOut shape. Note: `name` (not `display_name`), `role` (not `my_role`). */
export type WorkspaceSummary = components["schemas"]["WorkspaceOut"];
/** Alias for detail views — same shape as WorkspaceSummary in v2. */
export type WorkspaceDetail = components["schemas"]["WorkspaceOut"];
/** v2 WorkspaceMemberOut shape. Note: member has nested `user: UserRefOut`. */
export type WorkspaceMember = components["schemas"]["WorkspaceMemberOut"];
export type WorkspaceRole = "owner" | "editor" | "viewer";

// ---------------------------------------------------------------------------
// Legacy-only types not in v2 schema (DRF endpoints still serve these)
// ---------------------------------------------------------------------------

export interface DriveConfig {
  service_account_email: string;
}

export interface VerifyResult {
  ok: true;
  sample_files: { name: string; mime_type: string }[];
  total_visible: number;
}

export interface InviteCreated {
  token: string;
  email: string;
  role: WorkspaceRole;
  expires_at: string;
  accept_url: string;
}

export interface InvitePreview {
  workspace_slug: string;
  workspace_display_name: string;
  role: WorkspaceRole;
  invited_by_email: string;
  email: string;
  expires_at: string;
}

export interface AcceptResult {
  workspace_slug: string;
  role: WorkspaceRole;
  newly_joined: boolean;
}

export interface ActivityRow {
  action: string;
  subject: string;
  scopes_used: string[];
  context: Record<string, unknown>;
  created_at: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function listWorkspaces(): Promise<WorkspaceSummary[]> {
  const { data, error } = await apiV2.GET("/api/v2/workspaces");
  if (error) throw new Error((error as { title?: string }).title || "Failed to list workspaces");
  return data as WorkspaceSummary[];
}

export async function createWorkspace(input: {
  name: string;
  drive_root_folder_id: string;
  slug?: string;
}): Promise<WorkspaceDetail> {
  const body: components["schemas"]["WorkspaceCreateIn"] = {
    slug: input.slug ?? slugify(input.name),
    name: input.name,
    drive_root_folder_id: input.drive_root_folder_id,
  };
  const { data, error, response } = await apiV2.POST("/api/v2/workspaces", { body });
  if (error) throw new Error((error as { title?: string }).title || "Failed to create workspace");
  if (data) return data as WorkspaceDetail;
  return (await response.json()) as WorkspaceDetail;
}

export async function getWorkspace(slug: string): Promise<WorkspaceDetail> {
  const { data, error } = await apiV2.GET("/api/v2/workspaces/{slug}", {
    params: { path: { slug } },
  });
  if (error) throw new Error((error as { title?: string }).title || "Failed to get workspace");
  return data;
}

export async function updateWorkspace(
  slug: string,
  input: { name?: string; drive_root_folder_id?: string },
): Promise<WorkspaceDetail> {
  const { data, error } = await apiV2.PATCH("/api/v2/workspaces/{slug}", {
    params: { path: { slug } },
    body: input,
  });
  if (error) throw new Error((error as { title?: string }).title || "Failed to update workspace");
  return data;
}

export async function listMembers(slug: string): Promise<WorkspaceMember[]> {
  const { data, error } = await apiV2.GET("/api/v2/workspaces/{slug}/members", {
    params: { path: { slug } },
  });
  if (error) throw new Error((error as { title?: string }).title || "Failed to list members");
  return data as WorkspaceMember[];
}

export async function inviteMember(
  slug: string,
  input: { email: string; role: WorkspaceRole },
): Promise<InviteCreated> {
  const body: components["schemas"]["WorkspaceInviteIn"] = {
    email: input.email,
    role: input.role,
  };
  const { data, error } = await apiV2.POST(
    "/api/v2/workspaces/{slug}/members/invite",
    { params: { path: { slug } }, body },
  );
  if (error) throw new Error((error as { title?: string }).title || "Failed to invite member");
  if (!data) throw new Error("Failed to invite member: empty response");
  const out = data as components["schemas"]["WorkspaceInviteOut"];
  return {
    token: out.token,
    email: out.email,
    role: out.role,
    expires_at: out.updated_at, // best available timestamp
    accept_url: "",             // not in v2 schema
  };
}

export async function removeMember(slug: string, userId: number): Promise<void> {
  const { response } = await apiV2.DELETE("/api/v2/workspaces/{slug}/members/{user_id}", {
    params: { path: { slug, user_id: userId } },
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`Remove member failed: ${response.status}`);
  }
}

export async function changeMemberRole(
  slug: string,
  userId: number,
  role: WorkspaceRole,
): Promise<WorkspaceMember> {
  // v2 doesn't have a PATCH member endpoint — keep using legacy DRF.
  return apiFetch<WorkspaceMember>(`/api/workspaces/${slug}/members/${userId}/`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  }) as Promise<WorkspaceMember>;
}

export async function leaveWorkspace(slug: string): Promise<void> {
  const { response } = await apiV2.POST("/api/v2/workspaces/{slug}/leave", {
    params: { path: { slug } },
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`Leave workspace failed: ${response.status}`);
  }
}

export function getInvitePreview(token: string): Promise<InvitePreview> {
  return apiFetch<InvitePreview>(`/api/invites/${token}/`);
}

export function acceptInvite(token: string): Promise<AcceptResult> {
  return apiFetch<AcceptResult>(`/api/invites/${token}/accept/`, { method: "POST" });
}

export function getDriveConfig(): Promise<DriveConfig> {
  return apiFetch<DriveConfig>("/api/workspaces/drive-config/");
}

export function verifyDriveAccess(slug: string): Promise<VerifyResult> {
  // v2 endpoint exists but content?: never — use legacy for now
  return apiFetch<VerifyResult>(`/api/workspaces/${slug}/verify-drive-access/`, {
    method: "POST",
  });
}

export function listActivity(slug: string): Promise<ActivityRow[]> {
  return apiFetch<ActivityRow[]>(`/api/workspaces/${slug}/activity/`);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}
