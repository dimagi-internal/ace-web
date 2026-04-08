import { useState, type KeyboardEvent } from "react";

interface Props {
  disabled: boolean;
  isStreaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}

export function SendBox({ disabled, isStreaming, onSend, onStop }: Props) {
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
    <div className="flex items-end gap-2 border-t border-zinc-200 p-3">
      <textarea
        className="flex-1 resize-none rounded border border-zinc-300 px-3 py-2 outline-none focus:border-blue-500"
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
          className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50 hover:bg-blue-700"
        >
          Send
        </button>
      )}
    </div>
  );
}
