import { useCallback, useEffect, useState } from "react";

import { listSessions } from "../api/sessions";
import type { Session } from "../api/types";

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

  return { sessions, loading, refresh };
}
