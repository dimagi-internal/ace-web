import { apiFetch } from "./client";

export type WorkspaceRole = "owner" | "editor" | "viewer";

export interface WorkspaceSummary {
  slug: string;
  display_name: string;
  role: WorkspaceRole | null;
  created_at: string;
}

export interface WorkspaceMember {
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

export function listWorkspaces(): Promise<WorkspaceSummary[]> {
  return apiFetch<WorkspaceSummary[]>("/api/workspaces/");
}

export function getWorkspace(slug: string): Promise<WorkspaceDetail> {
  return apiFetch<WorkspaceDetail>(`/api/workspaces/${slug}/`);
}

export function getDriveConfig(): Promise<DriveConfig> {
  return apiFetch<DriveConfig>("/api/workspaces/drive-config/");
}
