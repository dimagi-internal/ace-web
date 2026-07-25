import { useEffect, useState } from "react";

import { apiClient } from "../api/apiClient";

/**
 * useCanopyStatus — the canopy hosted-chat feature flag + connection info.
 *
 * Mirrors `useCliAuthStatus`'s shape (a hook wrapping one ace endpoint) but
 * fetches exactly once and shares that result across every mount via a
 * module-level cache — this doesn't change at runtime the way CLI auth
 * status does, so polling would just be wasted requests. `null` means
 * "still loading" (or the one fetch failed); most callers should treat that
 * the same as "chat disabled" rather than blocking on it. A caller that
 * needs to tell those two apart (e.g. to stop showing "Loading…" forever on
 * a fetch failure) uses the sibling `useCanopyStatusFailed()` below —
 * Ledger minor: `CanopyChatRoutePage` previously had no way to distinguish
 * them and rendered "Loading…" forever on a status blip.
 */
export interface CanopyStatus {
  enabled: boolean;
  base_url: string;
  workspace: string;
  agent: string;
}

let cache: CanopyStatus | null = null;
let cacheFailed = false;
let inflight: Promise<CanopyStatus> | null = null;

async function fetchStatus(): Promise<CanopyStatus> {
  const { response } = await apiClient.GET("/api/canopy/status");
  if (!response.ok) {
    throw new Error(`Failed to fetch canopy status: ${response.status}`);
  }
  return (await response.json()) as CanopyStatus;
}

interface StatusState {
  status: CanopyStatus | null;
  failed: boolean;
}

/** Shared subscribe logic behind both `useCanopyStatus` and
 *  `useCanopyStatusFailed` — a single module-level cache/inflight-promise
 *  pair, so mounting both hooks at once still fires exactly one fetch. */
function useCanopyStatusState(): StatusState {
  const [state, setState] = useState<StatusState>({ status: cache, failed: cacheFailed });

  useEffect(() => {
    if (cache) {
      setState({ status: cache, failed: false });
      return;
    }

    let cancelled = false;
    if (!inflight) {
      inflight = fetchStatus()
        .then((result) => {
          cache = result;
          cacheFailed = false;
          return result;
        })
        .catch((err) => {
          // Don't poison future mounts with a permanent rejection — a later
          // mount (e.g. after a transient network blip) gets to try again.
          inflight = null;
          cacheFailed = true;
          throw err;
        });
    }
    inflight
      .then((result) => {
        if (!cancelled) setState({ status: result, failed: false });
      })
      .catch(() => {
        if (!cancelled) setState({ status: null, failed: true });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}

export function useCanopyStatus(): CanopyStatus | null {
  return useCanopyStatusState().status;
}

/** Whether the most recent status fetch failed. Both "still loading" and
 *  "fetch failed" surface as `useCanopyStatus() === null` — this is the only
 *  way to tell them apart, for a caller that needs to stop showing a
 *  perpetual "Loading…" and render a visible error/redirect instead. */
export function useCanopyStatusFailed(): boolean {
  return useCanopyStatusState().failed;
}
