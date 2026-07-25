import { useEffect, useState } from "react";

import { apiClient } from "../api/apiClient";

/**
 * useCanopyStatus — the canopy hosted-chat feature flag + connection info.
 *
 * Mirrors `useCliAuthStatus`'s shape (a hook wrapping one ace endpoint) but
 * fetches exactly once and shares that result across every mount via a
 * module-level cache — this doesn't change at runtime the way CLI auth
 * status does, so polling would just be wasted requests. `null` means
 * "still loading" (or the one fetch failed); callers should treat that the
 * same as "chat disabled" rather than blocking on it.
 */
export interface CanopyStatus {
  enabled: boolean;
  base_url: string;
  workspace: string;
  agent: string;
}

let cache: CanopyStatus | null = null;
let inflight: Promise<CanopyStatus> | null = null;

async function fetchStatus(): Promise<CanopyStatus> {
  // Not in generated.ts yet — see the note on token.ts's requestToken().
  const { response } = await apiClient.GET("/api/canopy/status" as never);
  if (!response.ok) {
    throw new Error(`Failed to fetch canopy status: ${response.status}`);
  }
  return (await response.json()) as CanopyStatus;
}

export function useCanopyStatus(): CanopyStatus | null {
  const [status, setStatus] = useState<CanopyStatus | null>(cache);

  useEffect(() => {
    if (cache) {
      setStatus(cache);
      return;
    }

    let cancelled = false;
    if (!inflight) {
      inflight = fetchStatus()
        .then((result) => {
          cache = result;
          return result;
        })
        .catch((err) => {
          // Don't poison future mounts with a permanent rejection — a later
          // mount (e.g. after a transient network blip) gets to try again.
          inflight = null;
          throw err;
        });
    }
    inflight
      .then((result) => {
        if (!cancelled) setStatus(result);
      })
      .catch(() => {
        if (!cancelled) setStatus(null);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return status;
}
