import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import type { Draft } from "../api/types";
import { IDLE_THRESHOLD_MS, isDraftIdle, msUntilDraftIdle } from "../lib/drafts";

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
  // Force a re-render when the lock transitions from live to idle.
  // Without this, nothing would trigger a re-render exactly at T+2s
  // after the last edit, and another user's UI would stay locked
  // indefinitely until some unrelated event happens to arrive.
  const [, forceTick] = useState(0);

  useEffect(() => {
    if (!draft) return;
    const remaining = msUntilDraftIdle(draft);
    if (remaining === 0) return;
    const t = window.setTimeout(
      () => forceTick((n) => n + 1),
      remaining + 10,
    );
    return () => window.clearTimeout(t);
  }, [draft?.last_edit_at, draft]);

  const holderId = draft?.last_editor ?? null;
  const isHolder = holderId != null && holderId === currentUserId;
  const holderIsIdle = isDraftIdle(draft);

  // Gate on draft existence: during the pre-session.state window the
  // textarea would otherwise accept keystrokes that silently drop
  // because the hook's updateDraft no-ops when active_draft is null.
  const canEdit =
    draft != null && (isHolder || holderIsIdle || !holderIsPresent);

  useEffect(() => {
    if (canEdit && !isHolder && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [canEdit, isHolder]);

  const body = draft?.body ?? "";
  const canSend = canEdit && body.trim().length > 0 && !isStreaming;

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // `isComposing` is true during IME input (CJK, etc.). Pressing
    // Enter to commit a composition must not send the message.
    const isComposing = (e.nativeEvent as unknown as { isComposing?: boolean })
      .isComposing;
    if (e.key === "Enter" && !e.shiftKey && !isComposing) {
      e.preventDefault();
      if (canSend) onSend();
    }
  };

  const handleStopClick = () => {
    if (streamingMessageId != null) onStop(streamingMessageId);
  };

  const placeholder = draft
    ? canEdit
      ? "Type a message… (Enter to send, Shift+Enter for newline)"
      : "Another teammate is editing…"
    : "Connecting…";

  return (
    <div className="border-t border-zinc-200 p-2">
      <textarea
        ref={textareaRef}
        value={body}
        disabled={!canEdit}
        onChange={(e) => onUpdate(e.target.value)}
        onKeyDown={handleKey}
        placeholder={placeholder}
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
            onClick={onTakeOver}
            className="rounded border border-zinc-300 px-3 py-1 text-sm text-zinc-700 hover:bg-zinc-100"
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

// Re-export for any consumer that still imports the threshold from
// SendBox (none should, but keeps the symbol stable).
export { IDLE_THRESHOLD_MS };
