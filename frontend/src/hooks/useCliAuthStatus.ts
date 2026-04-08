import { useEffect, useState } from "react";

import { cliAuthStatus } from "../api/auth";

export function useCliAuthStatus(pollIntervalMs = 30000) {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      try {
        const result = await cliAuthStatus();
        if (!cancelled) setAuthenticated(result.authenticated);
      } catch {
        if (!cancelled) setAuthenticated(false);
      }
    };
    tick();
    const id = setInterval(tick, pollIntervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [pollIntervalMs]);

  return authenticated;
}
