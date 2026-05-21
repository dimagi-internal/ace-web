import { AlertTriangle, ChevronRight, OctagonX } from "lucide-react";

import type { Message } from "../api/types.ws";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { ToolCallPair } from "./chat/ToolCallPair";

interface Props {
  message: Message;
  /** When set, expand/collapse this row regardless of native toggle. Lets
   *  MessageList's toolbar drive bulk expand/collapse without having to
   *  duplicate the rendering logic per row. */
  forceToolOpen?: boolean;
}

/** Count visible lines for the "▸ System context (N lines)" header. */
function countLines(text: string): number {
  if (!text) return 0;
  return text.split("\n").length;
}

// The backend marks cancelled-by-user turns as status=error with
// error_detail prefixed by "cancelled". Treat that visually as a
// neutral "stopped" state, not a scary "error" state.
function classifyError(detail: string | null) {
  const text = (detail ?? "").trim();
  if (text.toLowerCase().startsWith("cancelled")) {
    return {
      kind: "stopped" as const,
      label: text.replace(/^cancelled/i, "Stopped").trim() || "Stopped",
    };
  }
  return {
    kind: "error" as const,
    label: text || "Something went wrong",
  };
}

export function MessageItem({ message, forceToolOpen }: Props) {
  const text = message.plaintext;
  const isStreaming = message.status === "streaming";
  const isPending = message.status === "pending";
  const isError = message.status === "error";

  // tool_use and tool_result rows that survived the pairing pass in
  // MessageList didn't find a partner — render as standalone with the
  // same component for visual consistency. The common case (paired
  // tool_use+tool_result) is rendered by MessageList itself via
  // ToolCallPair so we never reach here for those.
  if (message.role === "tool_use") {
    return <ToolCallPair use={message} result={null} forceOpen={forceToolOpen} />;
  }
  if (message.role === "tool_result") {
    // Synthesize a fake "use" message so the pair component can render
    // a uniform header. Defensive — should be rare.
    const fakeUse: Message = {
      ...message,
      role: "tool_use",
      content: { name: "tool_result (orphan)" },
    };
    return <ToolCallPair use={fakeUse} result={message} forceOpen={forceToolOpen} />;
  }

  // System messages are seed context for the agent (e.g. the "Discuss this
  // step" prompt from the Opp Workbench): load-bearing for the assistant's
  // first response, but a wall-of-text from the human reader's POV. Render
  // collapsed by default with a chevron header so the send box stays the
  // focal point on session open. Issue #485.
  if (message.role === "system") {
    return <SystemSeedRow message={message} forceOpen={forceToolOpen} />;
  }

  const bubbleClass =
    message.role === "user"
      ? "ml-auto bg-primary text-primary-foreground"
      : "mr-auto bg-muted text-foreground";
  // Hold the "Thinking…" treatment through the gap between
  // chat.stream_start (status flips to "streaming") and the first
  // chat.delta (text becomes non-empty). Without `|| isStreaming`,
  // the bubble collapsed to just a 1px floating cursor for that
  // 100-300ms window — visible bubble-collapse stutter every turn.
  const showThinking =
    (isPending || isStreaming) && message.role === "assistant" && !text;
  return (
    <div
      className={`my-2 max-w-[80%] rounded-2xl px-4 py-2 ${bubbleClass}`}
      aria-live={isStreaming || isPending ? "polite" : undefined}
    >
      {showThinking ? (
        <span className="inline-flex items-center gap-1.5 text-muted-foreground">
          <span
            className="inline-flex gap-0.5"
            aria-label="Claude is thinking"
          >
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.3s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.15s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current" />
          </span>
          <span className="text-xs italic">Thinking…</span>
        </span>
      ) : message.role === "assistant" ? (
        <MarkdownRenderer content={text} variant="chat" />
      ) : (
        <div className="whitespace-pre-wrap">{text}</div>
      )}
      {isStreaming && text && (
        <span className="ml-1 inline-block h-3 w-1 animate-pulse bg-current align-middle" />
      )}
      {isError && message.role === "assistant" && (
        <ErrorFooter detail={message.error_detail} hasPartial={Boolean(text)} />
      )}
    </div>
  );
}

/**
 * Collapsed-by-default rendering for a seed/system message. The agent
 * already received the full prompt — this is purely a viewport-eating fix
 * so the user sees their send box, not 60 lines of orchestrator context.
 *
 * Uses a native <details> element so it's keyboard-accessible and
 * screen-reader friendly out of the box. ``forceToolOpen`` (driven by
 * MessageList's bulk toolbar) overrides the native state to match the
 * surrounding tool rows.
 */
function SystemSeedRow({
  message,
  forceOpen,
}: {
  message: Message;
  forceOpen: boolean | undefined;
}) {
  const text = message.plaintext;
  const lineCount = countLines(text);
  // ``open`` is undefined → native <details> behaviour (closed, toggleable).
  // ``open={true|false}`` → forced state, but still toggleable on click —
  // matches ToolCallPair semantics.
  const openProp = forceOpen === undefined ? undefined : forceOpen;
  return (
    <details
      className="my-2 mr-auto max-w-[80%] rounded-2xl border border-border bg-muted/40 px-3 py-1.5 text-sm group"
      data-testid="system-seed-row"
      {...(openProp !== undefined ? { open: openProp } : {})}
    >
      <summary className="flex cursor-pointer items-center gap-1.5 text-muted-foreground hover:text-foreground select-none list-none [&::-webkit-details-marker]:hidden">
        <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
        <span className="text-xs font-medium uppercase tracking-wide">
          System context
        </span>
        {lineCount > 0 && (
          <span className="text-xs text-muted-foreground/70">
            · {lineCount} line{lineCount === 1 ? "" : "s"}
          </span>
        )}
      </summary>
      <div className="mt-2 border-t border-border/40 pt-2 text-foreground">
        <MarkdownRenderer content={text} variant="chat" />
      </div>
    </details>
  );
}

function ErrorFooter({
  detail,
  hasPartial,
}: {
  detail: string | null;
  hasPartial: boolean;
}) {
  const { kind, label } = classifyError(detail);
  const isStopped = kind === "stopped";
  // Stopped = neutral muted treatment; error = amber warning. Avoid
  // destructive red — even a real CLI error is recoverable (the user
  // resends the next turn) and red bubbles reflexively read as "your
  // chat is broken".
  const Icon = isStopped ? OctagonX : AlertTriangle;
  const tone = isStopped
    ? "text-muted-foreground"
    : "text-amber-700 dark:text-amber-300";
  return (
    <div
      className={`mt-2 flex items-start gap-1.5 border-t border-border/40 pt-1.5 text-xs italic ${tone}`}
      role="status"
    >
      <Icon className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
      <span>
        {label}
        {hasPartial ? " · partial response shown above" : ""}
      </span>
    </div>
  );
}
