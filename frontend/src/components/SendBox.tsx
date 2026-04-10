import { useState, type KeyboardEvent } from "react";

interface Props {
  disabled: boolean;
  isStreaming: boolean;
  sessionSource?: string;
  sessionStatus?: string;
  onSend: (text: string) => void;
  onStop: () => void;
}

export function SendBox({ disabled, isStreaming, sessionSource, sessionStatus, onSend, onStop }: Props) {
  const [text, setText] = useState("");

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="border-t border-border">
      {sessionSource === "upload" && sessionStatus === "imported" && (
        <div className="px-3 py-1.5 text-xs text-muted-foreground border-b border-border bg-muted/50">
          Imported session — send a message to continue it with Claude.
        </div>
      )}
      <div className="flex items-end gap-2 p-3">
      <textarea
        className="flex-1 resize-none rounded border border-border bg-background px-3 py-2 text-foreground outline-none focus:border-ring"
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        disabled={disabled && !isStreaming}
        placeholder="Type a message…"
      />
      {isStreaming ? (
        <button
          type="button"
          onClick={onStop}
          className="rounded bg-red-600 px-4 py-2 text-white hover:bg-red-700"
        >
          Stop
        </button>
      ) : (
        <button
          type="button"
          onClick={submit}
          disabled={disabled || !text.trim()}
          className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50 hover:bg-primary/90"
        >
          Send
        </button>
      )}
      </div>
    </div>
  );
}
