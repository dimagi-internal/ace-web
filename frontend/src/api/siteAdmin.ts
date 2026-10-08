import { apiClient } from "./apiClient";
import type { components } from "./generated";

export type SiteAdminUser = components["schemas"]["SiteAdminUserOut"];
export type StaffChange = components["schemas"]["StaffChangeOut"];
export type SiteAdminUsers = components["schemas"]["SiteAdminUsersOut"];

/** The server's problem+json `detail` when it has one (the 409 guards do). */
function problemMessage(error: unknown, fallback: string): string {
  const p = error as { detail?: string; title?: string } | undefined;
  return p?.detail || p?.title || fallback;
}

export async function listSiteAdminUsers(q = ""): Promise<SiteAdminUsers> {
  const { data, error } = await apiClient.GET("/api/site-admin/users", {
    params: { query: { q } },
  });
  if (error || !data) throw new Error(problemMessage(error, "Failed to load users"));
  return data as SiteAdminUsers;
}

export async function setUserStaff(userId: number, isStaff: boolean): Promise<SiteAdminUser> {
  const { data, error } = await apiClient.PATCH("/api/site-admin/users/{user_id}", {
    params: { path: { user_id: userId } },
    body: { is_staff: isStaff },
  });
  if (error || !data) throw new Error(problemMessage(error, "Failed to update site admin"));
  return data as SiteAdminUser;
}
