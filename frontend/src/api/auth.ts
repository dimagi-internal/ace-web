import { apiClient } from "./apiClient";
import type { components } from "./generated";
import type { CliAuthPromoteResult, CliAuthStatus, NovaAuthStatus } from "./types.ws";

type NovaAuthStatusOut = components["schemas"]["NovaAuthStatusOut"];
type MeOut = components["schemas"]["MeOut"];

export const cliAuthStatus = async (): Promise<CliAuthStatus> => {
  const { data, error } = await apiClient.GET("/api/auth/cli/status");
  if (error) throw new Error((error as { title?: string }).title || "Failed to get CLI auth status");
  // data is typed as CliAuthStatusOut; v2 uses global_ to avoid Python keyword clash
  return {
    authenticated: data.authenticated,
    user: data.user as { has_blob: boolean; token_prefix: string | null },
    global: (data.global_ ?? (data as unknown as { global: { has_blob: boolean } }).global) as { has_blob: boolean },
  };
};

export const promoteCliAuthToGlobal = async (): Promise<CliAuthPromoteResult> => {
  // openapi-fetch CONSUMES the body to build `data` (dist/index.mjs) and never
  // clones, so `response.json()` here throws "body stream already read" on every
  // call. Use the parsed `data`. Same defect as useCanopyStatus — see #749.
  const { data: body, error, response } = await apiClient.POST(
    "/api/auth/cli/promote" as never, {} as never);
  if (!response.ok || error || !body) throw new Error(`Promote failed: ${response.status}`);
  const data = body as CliAuthPromoteResult;
  return data;
};

export const novaAuthStatus = async (): Promise<NovaAuthStatus> => {
  const { data, error } = await apiClient.GET("/api/auth/nova/status");
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
  // openapi-fetch CONSUMES the body to build `data` (dist/index.mjs) and never
  // clones, so `response.json()` here throws "body stream already read" on every
  // call. Use the parsed `data`. Same defect as useCanopyStatus — see #749.
  const { data, error, response } = await apiClient.POST("/api/auth/nova/disconnect", {});
  if (!response.ok || error || !data) {
    throw new Error(`Nova disconnect failed: ${response.status}`);
  }
  return data as { disconnected: boolean };
};

export interface CurrentUser {
  user_id: number;
  email: string;
  display_name: string;
}

export const getCurrentUser = async (): Promise<CurrentUser> => {
  const { data, response } = await apiClient.GET("/api/auth/me");
  if (data) {
    const out: MeOut = data as MeOut;
    return { user_id: out.id, email: out.email, display_name: out.display_name };
  }
  // The `content?: never` fallback for some schema versions. It can no longer
  // read the body — openapi-fetch already consumed it — so there is nothing to
  // parse and a second read would throw a confusing TypeError instead of saying
  // what went wrong. If `data` was empty, that IS the failure.
  throw new Error(`me: API client parsed no body (status ${response.status})`);
};
