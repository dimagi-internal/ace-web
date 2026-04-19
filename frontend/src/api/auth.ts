import { apiFetch } from "./client";
import type { CliAuthPromoteResult, CliAuthStatus } from "./types";

export const cliAuthStatus = () =>
  apiFetch<CliAuthStatus>("/api/auth/cli/status");

export const promoteCliAuthToGlobal = () =>
  apiFetch<CliAuthPromoteResult>("/api/auth/cli/promote", {
    method: "POST",
  });
