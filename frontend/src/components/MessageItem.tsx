import type { Message } from "../api/types";

interface Props {
  message: Message;
  liveText?: string;
  isLive?: boolean;
}

export function MessageItem({ message, liveText, isLive }: Props) {
  const text = isLive ? liveText ?? message.plaintext : message.plaintext;

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
  return (
    <div
      className={`my-2 max-w-[80%] rounded-2xl px-4 py-2 ${bubbleClass}`}
      aria-live={isLive ? "polite" : undefined}
    >
      <div className="whitespace-pre-wrap">{text}</div>
      {isLive && message.status === "streaming" && (
        <span className="ml-1 inline-block h-3 w-1 animate-pulse bg-current align-middle" />
      )}
    </div>
  );
}
