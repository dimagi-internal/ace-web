import { useCallback, useEffect, useRef } from "react";

import { wsUrl } from "../lib/wsUrl";

interface DecisionEditEvent {
  row_id: string;
  new_answer: string;
  override_reasoning?: string;
  editor_email: string;
  editor_name: string;
}

interface Options {
  slug: string;
  runId?: string;
  onOppUpdated?: () => void;
  onDecisionEdited?: (edit: DecisionEditEvent) => void;
  onDecisionReverted?: (data: { row_id: string; editor_email: string }) => void;
}

export function useOppSocket({ slug, runId, onOppUpdated, onDecisionEdited, onDecisionReverted }: Options) {
  const handlerRef = useRef({ onOppUpdated, onDecisionEdited, onDecisionReverted });
  handlerRef.current = { onOppUpdated, onDecisionEdited, onDecisionReverted };

  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!slug) return;
    const suffix = runId ? `/runs/${encodeURIComponent(runId)}/` : "/";
    const url = wsUrl(`ws/opps/${encodeURIComponent(slug)}${suffix}`);
    let ws: WebSocket | null = null;
    let closedByCleanup = false;
    let reconnectTimer: number | null = null;

    function open() {
      ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          const event = msg.event;
          if (event === "opp.updated") handlerRef.current.onOppUpdated?.();
          else if (event === "decision.edited") handlerRef.current.onDecisionEdited?.(msg.data);
          else if (event === "decision.reverted") handlerRef.current.onDecisionReverted?.(msg.data);
        } catch {
          // ignore malformed frames
        }
      };
      ws.onclose = () => {
        wsRef.current = null;
        if (closedByCleanup) return;
        reconnectTimer = window.setTimeout(open, 2000);
      };
    }
    open();

    return () => {
      closedByCleanup = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      ws?.close();
      wsRef.current = null;
    };
  }, [slug, runId]);

  const sendDecisionEdit = useCallback(
    (row_id: string, new_answer: string, override_reasoning?: string) => {
      wsRef.current?.send(
        JSON.stringify({
          type: "decision.edit",
          row_id,
          new_answer,
          override_reasoning: override_reasoning ?? "",
        }),
      );
    },
    [],
  );

  const sendDecisionRevert = useCallback((row_id: string) => {
    wsRef.current?.send(JSON.stringify({ type: "decision.revert", row_id }));
  }, []);

  return { sendDecisionEdit, sendDecisionRevert };
}
