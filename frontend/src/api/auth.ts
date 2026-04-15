import { apiFetch } from "./client";
import type {
  CliAuthPollResult,
  CliAuthStartResult,
  CliAuthStatus,
} from "./types";

export const cliAuthStatus = () =>
  apiFetch<CliAuthStatus>("/api/auth/cli/status");

export const cliAuthStart = () =>
  apiFetch<CliAuthStartResult>("/api/auth/cli/start", { method: "POST" });

export const cliAuthComplete = (code: string) =>
  apiFetch<{ status: string; token_set: boolean }>(
    "/api/auth/cli/complete",
    { method: "POST", body: JSON.stringify({ code }) },
  );

export const cliAuthPoll = () =>
  apiFetch<CliAuthPollResult>("/api/auth/cli/poll");

export const cliAuthCancel = () =>
  apiFetch<{ cancelled: boolean }>(
    "/api/auth/cli/cancel",
    { method: "POST" },
  );
