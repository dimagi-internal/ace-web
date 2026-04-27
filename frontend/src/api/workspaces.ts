import { apiFetch } from "./client";

export type WorkspaceRole = "owner" | "editor" | "viewer";

export interface WorkspaceSummary {
  slug: string;
  display_name: string;
  role: WorkspaceRole | null;
  created_at: string;
}

export interface WorkspaceMember {
  user_id: number;
  user_email: string;
  user_display_name: string;
  role: WorkspaceRole;
  joined_at: string;
}

export interface WorkspaceDetail {
  slug: string;
  display_name: string;
  drive_root_folder_id: string;
  created_at: string;
  updated_at: string;
  settings: Record<string, unknown>;
  members: WorkspaceMember[];
  my_role: WorkspaceRole | null;
}

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

export function listWorkspaces(): Promise<WorkspaceSummary[]> {
  return apiFetch<WorkspaceSummary[]>("/api/workspaces/");
}

export function createWorkspace(input: {
  display_name: string;
  drive_root_folder_id: string;
  slug?: string;
}): Promise<WorkspaceDetail> {
  return apiFetch<WorkspaceDetail>("/api/workspaces/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getWorkspace(slug: string): Promise<WorkspaceDetail> {
  return apiFetch<WorkspaceDetail>(`/api/workspaces/${slug}/`);
}

export function verifyDriveAccess(slug: string): Promise<VerifyResult> {
  return apiFetch<VerifyResult>(`/api/workspaces/${slug}/verify-drive-access/`, {
    method: "POST",
  });
}

export function getDriveConfig(): Promise<DriveConfig> {
  return apiFetch<DriveConfig>("/api/workspaces/drive-config/");
}

export function listMembers(slug: string): Promise<WorkspaceMember[]> {
  return apiFetch<WorkspaceMember[]>(`/api/workspaces/${slug}/members/`);
}

export function inviteMember(
  slug: string,
  input: { email: string; role: WorkspaceRole },
): Promise<InviteCreated> {
  return apiFetch<InviteCreated>(`/api/workspaces/${slug}/members/`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function removeMember(slug: string, userId: number): Promise<void> {
  return apiFetch<void>(`/api/workspaces/${slug}/members/${userId}/`, {
    method: "DELETE",
  });
}

export function changeMemberRole(
  slug: string,
  userId: number,
  role: WorkspaceRole,
): Promise<WorkspaceMember> {
  return apiFetch<WorkspaceMember>(`/api/workspaces/${slug}/members/${userId}/`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export function getInvitePreview(token: string): Promise<InvitePreview> {
  return apiFetch<InvitePreview>(`/api/invites/${token}/`);
}

export function acceptInvite(token: string): Promise<AcceptResult> {
  return apiFetch<AcceptResult>(`/api/invites/${token}/accept/`, {
    method: "POST",
  });
}

export function leaveWorkspace(slug: string): Promise<void> {
  return apiFetch<void>(`/api/workspaces/${slug}/leave/`, {
    method: "POST",
  });
}

export interface ActivityRow {
  action: string;
  subject: string;
  scopes_used: string[];
  context: Record<string, unknown>;
  created_at: string;
}

export function listActivity(slug: string): Promise<ActivityRow[]> {
  return apiFetch<ActivityRow[]>(`/api/workspaces/${slug}/activity/`);
}
