import type { Message } from "../api/types";

interface Props {
  message: Message;
}

export function MessageItem({ message }: Props) {
  const text = message.plaintext;
  const isStreaming = message.status === "streaming";

  if (message.role === "tool_use") {
    return (
      <details className="my-2 rounded border border-zinc-200 bg-zinc-50 p-2 text-sm">
        <summary className="cursor-pointer text-zinc-600">
          tool_use: {String(message.content?.name ?? "unknown")}
        </summary>
        <pre className="mt-2 whitespace-pre-wrap text-xs text-zinc-700">
          {JSON.stringify(message.content, null, 2)}
        </pre>
      </details>
    );
  }
  if (message.role === "tool_result") {
    return (
      <details className="my-2 rounded border border-zinc-200 bg-zinc-50 p-2 text-sm">
        <summary className="cursor-pointer text-zinc-600">tool_result</summary>
        <pre className="mt-2 whitespace-pre-wrap text-xs text-zinc-700">
          {message.plaintext}
        </pre>
      </details>
    );
  }

  const bubbleClass =
    message.role === "user"
      ? "ml-auto bg-blue-600 text-white"
      : "mr-auto bg-zinc-100 text-zinc-900";
  return (
    <div
      className={`my-2 max-w-[80%] rounded-2xl px-4 py-2 ${bubbleClass}`}
      aria-live={isStreaming ? "polite" : undefined}
    >
      <div className="whitespace-pre-wrap">{text}</div>
      {isStreaming && (
        <span className="ml-1 inline-block h-3 w-1 animate-pulse bg-current align-middle" />
      )}
    </div>
  );
}
