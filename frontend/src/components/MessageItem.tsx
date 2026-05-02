import { AlertTriangle, OctagonX } from "lucide-react";

import type { Message } from "../api/types";
import { MarkdownRenderer } from "./MarkdownRenderer";

interface Props {
  message: Message;
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

export function MessageItem({ message }: Props) {
  const text = message.plaintext;
  const isStreaming = message.status === "streaming";
  const isPending = message.status === "pending";
  const isError = message.status === "error";

  if (message.role === "tool_use") {
    return (
      <details className="my-2 rounded border border-border bg-muted p-2 text-sm">
        <summary className="cursor-pointer text-muted-foreground">
          tool_use: {String(message.content?.name ?? "unknown")}
        </summary>
        <pre className="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">
          {JSON.stringify(message.content, null, 2)}
        </pre>
      </details>
    );
  }
  if (message.role === "tool_result") {
    return (
      <details className="my-2 rounded border border-border bg-muted p-2 text-sm">
        <summary className="cursor-pointer text-muted-foreground">tool_result</summary>
        <pre className="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">
          {message.plaintext}
        </pre>
      </details>
    );
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
