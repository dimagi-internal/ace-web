import { apiClient } from "./apiClient";
import type { components } from "./generated";

export type PresencePreference = components["schemas"]["PresencePreferenceOut"];

/**
 * Fetch the signed-in user's presence-visibility preference.
 *
 * Uses the typed `apiClient` (not a hand-rolled `fetch`) so the CSRF +
 * workspace-header middleware and the auth-redirect middleware apply the
 * same way every other v2 API call does — see api/apiClient.ts.
 */
export const getPresencePreference = async (): Promise<PresencePreference> => {
  const { data, error } = await apiClient.GET("/api/me/presence-preference");
  if (error) throw new Error((error as { title?: string }).title || "Failed to load presence preference");
  return data;
};

export const setPresencePreference = async (showPresence: boolean): Promise<PresencePreference> => {
  const { data, error } = await apiClient.PATCH("/api/me/presence-preference", {
    body: { show_presence: showPresence },
  });
  if (error) throw new Error((error as { title?: string }).title || "Failed to update presence preference");
  return data;
};
