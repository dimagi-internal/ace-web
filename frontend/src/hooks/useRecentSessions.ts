import { useCallback, useEffect, useState } from "react";

import { listSessions } from "../api/sessions";
import type { Session } from "../api/types.ws";

export const SESSIONS_UPDATED_EVENT = "ace:sessions-updated";

export function notifySessionsUpdated() {
  window.dispatchEvent(new CustomEvent(SESSIONS_UPDATED_EVENT));
}

export function useRecentSessions(limit = 10, workspaceSlug?: string) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!workspaceSlug) {
      setSessions([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const data = await listSessions({ pageSize: limit, status: "active", workspaceSlug });
    setSessions(data.items);
    setLoading(false);
  }, [limit, workspaceSlug]);

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
