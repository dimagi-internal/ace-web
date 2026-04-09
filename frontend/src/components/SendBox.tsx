import { useEffect, useRef } from "react";

import type { Draft } from "../api/types";

interface Props {
  draft: Draft | null;
  currentUserId: number;
  holderIsPresent: boolean;
  isStreaming: boolean;
  streamingMessageId: number | null;
  onUpdate: (body: string) => void;
  onSend: () => void;
  onStop: (messageId: number) => void;
  onTakeOver: () => void;
}

const IDLE_THRESHOLD_MS = 2_000;

export function SendBox({
  draft,
  currentUserId,
  holderIsPresent,
  isStreaming,
  streamingMessageId,
  onUpdate,
  onSend,
  onStop,
  onTakeOver,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const holderId = draft?.last_editor ?? null;
  const isHolder = holderId === currentUserId;
  const lastEditAt = draft ? new Date(draft.last_edit_at).getTime() : 0;
  const holderIsIdle = draft ? Date.now() - lastEditAt > IDLE_THRESHOLD_MS : true;
  // Textarea editable if: you are the holder OR the lock is idle OR the holder is absent.
  const canEdit = isHolder || holderIsIdle || !holderIsPresent;

  useEffect(() => {
    if (canEdit && !isHolder && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [canEdit, isHolder]);

  const body = draft?.body ?? "";
  const canSend = canEdit && body.trim().length > 0 && !isStreaming;

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend) onSend();
    }
  };

  const handleStopClick = () => {
    if (streamingMessageId != null) onStop(streamingMessageId);
  };

  return (
    <div className="border-t border-zinc-200 p-2">
      <textarea
        ref={textareaRef}
        value={body}
        readOnly={!canEdit}
        disabled={!canEdit}
        onChange={(e) => onUpdate(e.target.value)}
        onKeyDown={handleKey}
        placeholder={
          canEdit
            ? "Type a message… (Enter to send, Shift+Enter for newline)"
            : "Another teammate is editing…"
        }
        rows={3}
        className="w-full resize-none rounded border border-zinc-300 p-2 text-sm disabled:bg-zinc-50 disabled:text-zinc-500"
      />
      <div className="mt-1 flex justify-end gap-2">
        {isStreaming ? (
          <button
            type="button"
            onClick={handleStopClick}
            className="rounded bg-rose-600 px-3 py-1 text-sm text-white"
          >
            stop
          </button>
        ) : null}
        {!canEdit && holderIsPresent && !holderIsIdle ? (
          <button
            type="button"
            disabled
            onClick={onTakeOver}
            className="rounded border border-zinc-300 px-3 py-1 text-sm text-zinc-400"
          >
            take over
          </button>
        ) : null}
        <button
          type="button"
          disabled={!canSend}
          onClick={onSend}
          className="rounded bg-blue-600 px-3 py-1 text-sm text-white disabled:opacity-40"
        >
          send
        </button>
      </div>
    </div>
  );
}
