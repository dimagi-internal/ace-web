import { apiV2 } from "./client.v2";
import type { components } from "./generated";
import type { CliAuthPromoteResult, CliAuthStatus, NovaAuthStatus } from "./types.ws";

type NovaAuthStatusOut = components["schemas"]["NovaAuthStatusOut"];
type MeOut = components["schemas"]["MeOut"];

export const cliAuthStatus = async (): Promise<CliAuthStatus> => {
  const { data, error } = await apiV2.GET("/api/v2/auth/cli/status");
  if (error) throw new Error((error as { title?: string }).title || "Failed to get CLI auth status");
  // data is typed as CliAuthStatusOut; v2 uses global_ to avoid Python keyword clash
  return {
    authenticated: data.authenticated,
    user: data.user as { has_blob: boolean; token_prefix: string | null },
    global: (data.global_ ?? (data as unknown as { global: { has_blob: boolean } }).global) as { has_blob: boolean },
  };
};

export const promoteCliAuthToGlobal = async (): Promise<CliAuthPromoteResult> => {
  const { response } = await apiV2.POST("/api/v2/auth/cli/promote", {});
  if (!response.ok) throw new Error(`Promote failed: ${response.status}`);
  const data = (await response.json()) as CliAuthPromoteResult;
  return data;
};

export const novaAuthStatus = async (): Promise<NovaAuthStatus> => {
  const { data, error } = await apiV2.GET("/api/v2/auth/nova/status");
  if (error) throw new Error((error as { title?: string }).title || "Failed to get Nova auth status");
  const out: NovaAuthStatusOut = data;
  return {
    connected: out.connected,
    valid: out.valid,
    // v2 returns expires_at as ISO string; legacy consumers expect unix seconds
    expires_at: out.expires_at ? new Date(out.expires_at).getTime() / 1000 : null,
    scope: out.scope ?? null,
    can_manage: out.can_manage,
  };
};

export const disconnectNova = async (): Promise<{ disconnected: boolean }> => {
  const { response } = await apiV2.POST("/api/v2/auth/nova/disconnect", {});
  if (!response.ok) throw new Error(`Nova disconnect failed: ${response.status}`);
  return (await response.json()) as { disconnected: boolean };
};

export interface CurrentUser {
  user_id: number;
  email: string;
  display_name: string;
}

export const getCurrentUser = async (): Promise<CurrentUser> => {
  const { data, response } = await apiV2.GET("/api/v2/auth/me");
  if (data) {
    const out: MeOut = data as MeOut;
    return { user_id: out.id, email: out.email, display_name: out.display_name };
  }
  // content?: never path on some schema versions — parse raw
  const raw = (await response.json()) as MeOut;
  return { user_id: raw.id, email: raw.email, display_name: raw.display_name };
};
