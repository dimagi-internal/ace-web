import { apiFetch } from "./client";
import type { CliAuthStatus } from "./types";

export const cliAuthStatus = () =>
  apiFetch<CliAuthStatus>("/api/auth/cli/status");
