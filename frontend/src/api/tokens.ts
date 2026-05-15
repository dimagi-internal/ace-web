import { apiClient } from "./apiClient";
import type { components } from "./generated";

type PersonalTokenOut = components["schemas"]["PersonalTokenOut"];
type PersonalTokenCreatedOut = components["schemas"]["PersonalTokenCreatedOut"];

// ---------------------------------------------------------------------------
// v2 canonical types — exported for consumer files
// ---------------------------------------------------------------------------

/**
 * PersonalToken — v2 shape. Note: the field is `name` (not `label`).
 * Legacy consumers that referenced `label` need updating to `name`.
 */
export type PersonalToken = PersonalTokenOut;
export type PersonalTokenCreated = PersonalTokenCreatedOut;

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export const listTokens = async (): Promise<PersonalToken[]> => {
  const { data, error } = await apiClient.GET("/api/tokens");
  if (error) throw new Error((error as { title?: string }).title || "Failed to list tokens");
  return data as PersonalToken[];
};

export const createToken = async (name: string): Promise<PersonalTokenCreated> => {
  const { data, error } = await apiClient.POST("/api/tokens", {
    body: { name },
  });
  if (error) throw new Error((error as { title?: string }).title || "Failed to create token");
  return data as PersonalTokenCreated;
};

export const revokeToken = async (id: number): Promise<void> => {
  const { response } = await apiClient.DELETE("/api/tokens/{token_id}", {
    params: { path: { token_id: id } },
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`Revoke failed: ${response.status}`);
  }
};
