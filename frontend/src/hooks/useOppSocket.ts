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
  // Frames staged while no socket is OPEN (still connecting, or between
  // reconnects). Flushed on the next open — otherwise an edit made in
  // that gap renders locally but never reaches the shared Redis buffer,
  // and a later Save to Drive (which trusts the buffer) silently drops it.
  const pendingRef = useRef<string[]>([]);

  useEffect(() => {
    if (!slug) return;
    const suffix = runId ? `/runs/${encodeURIComponent(runId)}/` : "/";
    const url = wsUrl(`ws/opps/${encodeURIComponent(slug)}${suffix}`);
    let ws: WebSocket | null = null;
    let closedByCleanup = false;
    let reconnectTimer: number | null = null;

    function open() {
      const sock = new WebSocket(url);
      ws = sock;
      wsRef.current = sock;
      sock.onopen = () => {
        const queued = pendingRef.current.splice(0);
        for (const frame of queued) sock.send(frame);
      };
      sock.onmessage = (e) => {
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
      sock.onclose = () => {
        // Identity-guarded: close events land asynchronously, so a STALE
        // socket's close (e.g. the unscoped socket torn down when runId
        // resolves) can arrive after its replacement is already live.
        // Unconditionally nulling here clobbered the live ref and made
        // every subsequent send a silent no-op.
        if (wsRef.current === sock) wsRef.current = null;
        if (closedByCleanup) return;
        reconnectTimer = window.setTimeout(open, 2000);
      };
    }
    open();

    return () => {
      closedByCleanup = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      ws?.close();
      if (wsRef.current === ws) wsRef.current = null;
    };
  }, [slug, runId]);

  const sendFrame = useCallback((frame: string) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(frame);
    } else {
      // Not open (connecting / reconnect gap): a raw send() would throw
      // InvalidStateError. Queue instead; onopen flushes in order.
      pendingRef.current.push(frame);
    }
  }, []);

  const sendDecisionEdit = useCallback(
    (row_id: string, new_answer: string, override_reasoning?: string) => {
      sendFrame(
        JSON.stringify({
          type: "decision.edit",
          row_id,
          new_answer,
          override_reasoning: override_reasoning ?? "",
        }),
      );
    },
    [sendFrame],
  );

  const sendDecisionRevert = useCallback(
    (row_id: string) => {
      sendFrame(JSON.stringify({ type: "decision.revert", row_id }));
    },
    [sendFrame],
  );

  return { sendDecisionEdit, sendDecisionRevert };
}
