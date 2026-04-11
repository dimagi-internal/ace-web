import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import type { Draft, SessionSource, SessionStatus } from "../api/types";
import { IDLE_THRESHOLD_MS, isDraftIdle, msUntilDraftIdle } from "../lib/drafts";

interface Props {
  draft: Draft | null;
  currentUserId: number;
  holderIsPresent: boolean;
  isStreaming: boolean;
  streamingMessageId: number | null;
  sessionSource?: SessionSource;
  sessionStatus?: SessionStatus;
  cliConnected?: boolean | null;
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
  sessionSource,
  sessionStatus,
  cliConnected,
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
  // Block sends when the Claude CLI is explicitly known to be disconnected.
  // null means "still loading" — don't block in that window.
  const cliBlocked = cliConnected === false;
  const canSend = canEdit && body.trim().length > 0 && !isStreaming && !cliBlocked;

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

  const placeholder = !draft
    ? "Connecting…"
    : cliBlocked
      ? "Claude CLI not connected — visit /auth/cli to enable chat"
      : canEdit
        ? "Type a message… (Enter to send, Shift+Enter for newline)"
        : "Another teammate is editing…";

  return (
    <div className="border-t border-border bg-background">
      {sessionSource === "upload" && sessionStatus === "imported" && (
        <div className="border-b border-border bg-muted px-3 py-1.5 text-xs text-muted-foreground">
          Imported session — send a message to continue it with Claude.
        </div>
      )}
      <div className="p-2">
        <textarea
          ref={textareaRef}
          value={body}
          disabled={!canEdit}
          onChange={(e) => onUpdate(e.target.value)}
          onKeyDown={handleKey}
          placeholder={placeholder}
          rows={3}
          className="w-full resize-none rounded-md border border-input bg-transparent p-2 text-sm text-foreground shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
        />
        <div className="mt-1 flex justify-end gap-2">
          {isStreaming ? (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={handleStopClick}
            >
              stop
            </Button>
          ) : null}
          {!canEdit && holderIsPresent && !holderIsIdle ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onTakeOver}
            >
              take over
            </Button>
          ) : null}
          <Button
            type="button"
            size="sm"
            disabled={!canSend}
            onClick={onSend}
          >
            send
          </Button>
        </div>
      </div>
    </div>
  );
}

// Re-export for any consumer that still imports the threshold from
// SendBox (none should, but keeps the symbol stable).
export { IDLE_THRESHOLD_MS };
