import { useCallback, useEffect, useState } from "react";

import { listSessions } from "../api/sessions";
import type { Session } from "../api/types";

export const SESSIONS_UPDATED_EVENT = "ace:sessions-updated";

export function notifySessionsUpdated() {
  window.dispatchEvent(new CustomEvent(SESSIONS_UPDATED_EVENT));
}

export function useRecentSessions(limit = 10) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    const data = await listSessions({ pageSize: limit, status: "active" });
    setSessions(data.items);
    setLoading(false);
  }, [limit]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const handler = () => {
      void refresh();
    };
    window.addEventListener(SESSIONS_UPDATED_EVENT, handler);
    return () => window.removeEventListener(SESSIONS_UPDATED_EVENT, handler);
  }, [refresh]);

  return { sessions, loading, refresh };
}
