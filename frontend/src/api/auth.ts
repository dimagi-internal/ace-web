import { apiFetch } from "./client";
import type { CliAuthStatus } from "./types";

export const cliAuthStatus = () =>
  apiFetch<CliAuthStatus>("/api/auth/cli/status");

export const cliAuthSetToken = (token: string) =>
  apiFetch<CliAuthStatus>("/api/auth/cli/token", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
