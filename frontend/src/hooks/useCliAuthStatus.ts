import { useEffect, useState } from "react";

import { cliAuthStatus } from "../api/auth";

/**
 * Snapshot of the CLI auth status the chat UI cares about.
 *
 * ``hasBlob`` is the gate the send button reads: true iff EITHER a
 * user-scoped credential blob or the global fallback exists in the DB,
 * which is what ``CLIBackend._stage_env_for`` actually requires to spawn
 * a chat subprocess. ``authenticated`` reflects the (slow, expensive)
 * live ``claude -p`` check; on cold starts after an ECS task roll it can
 * briefly read false even when the blob is fine — see issue #479. We
 * surface that as a passive warning chip but do NOT block sends on it.
 *
 * ``null`` for either field means "still loading" — render as
 * indeterminate (no blocker, no warning).
 */
export interface CliAuthSnapshot {
  /** Live ``claude -p`` check passed (or null while loading). */
  authenticated: boolean | null;
  /** A credential blob exists in DB — chat backend can spawn (or null while loading). */
  hasBlob: boolean | null;
}

export function useCliAuthStatus(pollIntervalMs = 30000): CliAuthSnapshot {
  const [snapshot, setSnapshot] = useState<CliAuthSnapshot>({
    authenticated: null,
    hasBlob: null,
  });

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      try {
        const result = await cliAuthStatus();
        if (cancelled) return;
        setSnapshot({
          authenticated: result.authenticated,
          hasBlob: Boolean(result.user?.has_blob || result.global?.has_blob),
        });
      } catch {
        if (cancelled) return;
        // Network/auth error — treat both as false so the UI surfaces a
        // disconnected state instead of perpetual "loading".
        setSnapshot({ authenticated: false, hasBlob: false });
      }
    };
    tick();
    const id = setInterval(tick, pollIntervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [pollIntervalMs]);

  return snapshot;
}
