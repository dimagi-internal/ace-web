import { useEffect, useRef } from "react";

interface Options {
  slug: string;
  runId?: string;
  onOppUpdated?: () => void;
}

const WS_BASE = (() => {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  return `${protocol}//${window.location.host}${base}`;
})();

export function useOppSocket({ slug, runId, onOppUpdated }: Options) {
  // Keep the latest handler in a ref so re-renders don't recreate the
  // WebSocket connection on every prop change.
  const handlerRef = useRef(onOppUpdated);
  handlerRef.current = onOppUpdated;

  useEffect(() => {
    if (!slug) return;
    const suffix = runId ? `/runs/${encodeURIComponent(runId)}/` : "/";
    const url = `${WS_BASE}/ws/opps/${encodeURIComponent(slug)}${suffix}`;
    let ws: WebSocket | null = null;
    let closedByCleanup = false;
    let reconnectTimer: number | null = null;

    function open() {
      ws = new WebSocket(url);
      ws.onmessage = (e) => {
        try {
          const { event } = JSON.parse(e.data);
          if (event === "opp.updated") handlerRef.current?.();
        } catch {
          // ignore malformed frames
        }
      };
      ws.onclose = () => {
        if (closedByCleanup) return;
        // Single retry after 2s. Simple — production might want
        // exponential backoff, but the workbench is a low-traffic,
        // user-visible surface where a 2s gap is acceptable.
        reconnectTimer = window.setTimeout(open, 2000);
      };
    }
    open();

    return () => {
      closedByCleanup = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [slug, runId]);
}
