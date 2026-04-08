import { useEffect, useRef, useState } from "react";

import { streamUrl } from "../api/messages";

export type StreamPhase = "idle" | "streaming" | "complete" | "error" | "cancelled";

export interface ToolBlock {
  kind: "tool_use" | "tool_result";
  block: Record<string, unknown>;
}

export interface StreamingState {
  phase: StreamPhase;
  text: string;
  tools: ToolBlock[];
  error: string | null;
}

const INITIAL: StreamingState = {
  phase: "idle",
  text: "",
  tools: [],
  error: null,
};

/**
 * Opens an EventSource against /api/messages/<id>/stream and accumulates
 * delta text + tool blocks until done|error or the consumer cancels.
 */
export function useStreamingMessage(assistantMessageId: number | null) {
  const [state, setState] = useState<StreamingState>(INITIAL);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (assistantMessageId == null) {
      setState(INITIAL);
      return;
    }

    setState({ ...INITIAL, phase: "streaming" });
    const source = new EventSource(streamUrl(assistantMessageId));
    sourceRef.current = source;

    const onDelta = (e: MessageEvent) => {
      const payload = JSON.parse(e.data) as { text: string };
      setState((s) => ({ ...s, text: s.text + payload.text }));
    };
    const onToolUse = (e: MessageEvent) => {
      const payload = JSON.parse(e.data) as { block: Record<string, unknown> };
      setState((s) => ({
        ...s,
        tools: [...s.tools, { kind: "tool_use", block: payload.block }],
      }));
    };
    const onToolResult = (e: MessageEvent) => {
      const payload = JSON.parse(e.data) as { block: Record<string, unknown> };
      setState((s) => ({
        ...s,
        tools: [...s.tools, { kind: "tool_result", block: payload.block }],
      }));
    };
    const onDone = () => {
      setState((s) => ({ ...s, phase: "complete" }));
      source.close();
    };
    const onError = (e: MessageEvent) => {
      let message = "stream error";
      try {
        message = (JSON.parse(e.data) as { message: string }).message;
      } catch {
        // EventSource also fires generic error events with no data — leave default
      }
      setState((s) => ({ ...s, phase: "error", error: message }));
      source.close();
    };

    source.addEventListener("delta", onDelta);
    source.addEventListener("tool_use", onToolUse);
    source.addEventListener("tool_result", onToolResult);
    source.addEventListener("done", onDone);
    source.addEventListener("error", onError);

    return () => {
      source.close();
    };
  }, [assistantMessageId]);

  const cancel = () => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
      setState((s) => ({ ...s, phase: "cancelled" }));
    }
  };

  return { ...state, cancel };
}
