import { apiFetch } from "./client";
import type { CliAuthPromoteResult, CliAuthStatus, NovaAuthStatus } from "./types";

export const cliAuthStatus = () =>
  apiFetch<CliAuthStatus>("/api/auth/cli/status");

export const promoteCliAuthToGlobal = () =>
  apiFetch<CliAuthPromoteResult>("/api/auth/cli/promote", {
    method: "POST",
  });

export const novaAuthStatus = () =>
  apiFetch<NovaAuthStatus>("/api/auth/nova/status");

export const disconnectNova = () =>
  apiFetch<{ disconnected: boolean }>("/api/auth/nova/disconnect", {
    method: "POST",
  });

export interface CurrentUser {
  user_id: number;
  email: string;
  display_name: string;
}

export const getCurrentUser = () =>
  apiFetch<CurrentUser>("/auth/me/");
