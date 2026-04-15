import { useEffect, useMemo, useState } from "react";

import { getSession } from "../../api/sessions";
import type { Session } from "../../api/types";
import { useCliAuthStatus } from "../../hooks/useCliAuthStatus";
import { useSessionSocket } from "../../hooks/useSessionSocket";
import { isDraftIdle, msUntilDraftIdle } from "../../lib/drafts";
import { CliAuthBanner } from "../CliAuthBanner";
import { MessageList } from "../MessageList";
import { PresenceChips } from "../PresenceChips";
import { SendBox } from "../SendBox";

interface Props {
  slug: string;
}

/**
 * Reusable chat body: CLI auth banner, presence chips, message list, send box.
 *
 * This is the extracted body of ChatPage — the page adds its own chrome
 * (sidebar, title editor, share popover), but this component renders the
 * same chat surface whether it's in the dedicated chat page or embedded in
 * the Opp Workbench right-side panel.
 */
export function ChatPanel({ slug }: Props) {
  const [meta, setMeta] = useState<Session | null>(null);
  const socket = useSessionSocket(slug);
  const cliConnected = useCliAuthStatus();

  // Force a re-render when the draft lock transitions from live to idle
  // so PresenceChips' amber-highlight updates at T+2s without waiting for
  // some unrelated event to arrive. See docs/learnings/draft-soft-lock-idle-timer.md.
  const [, forceIdleTick] = useState(0);
  useEffect(() => {
    const draft = socket.state.active_draft;
    if (!draft) return;
    const remaining = msUntilDraftIdle(draft);
    if (remaining === 0) return;
    const t = window.setTimeout(
      () => forceIdleTick((n) => n + 1),
      remaining + 10,
    );
    return () => window.clearTimeout(t);
  }, [socket.state.active_draft?.last_edit_at, socket.state.active_draft]);

  useEffect(() => {
    if (!slug) return;
    getSession(slug)
      .then((s) => setMeta(s))
      .catch(() => setMeta(null));
  }, [slug]);

  const currentUserId = socket.state.current_user_id;
  const holderId = socket.state.active_draft?.last_editor ?? null;
  const holderIsPresent =
    holderId != null && socket.state.presence_user_ids.includes(holderId);

  const streamingMessage = useMemo(() => {
    return socket.state.messages.find((m) => m.status === "streaming") ?? null;
  }, [socket.state.messages]);

  if (!meta) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-sm text-muted-foreground">
        Loading chat…
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <CliAuthBanner />
      <div className="flex items-center gap-2 border-b border-border bg-background px-3 py-1.5 text-xs">
        <span className="truncate text-muted-foreground">{meta.title}</span>
        <div className="ml-auto">
          <PresenceChips
            participants={socket.state.participants}
            presenceUserIds={socket.state.presence_user_ids}
            draftHolderId={holderId}
            draftHolderIdle={isDraftIdle(socket.state.active_draft)}
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        <MessageList messages={socket.state.messages} />
      </div>
      <SendBox
        draft={socket.state.active_draft}
        currentUserId={currentUserId}
        holderIsPresent={holderIsPresent}
        isStreaming={streamingMessage != null}
        streamingMessageId={streamingMessage?.id ?? null}
        sessionSource={meta.source}
        sessionStatus={meta.status}
        cliConnected={cliConnected}
        onUpdate={socket.updateDraft}
        onSend={socket.sendChat}
        onStop={socket.stopChat}
        onTakeOver={socket.takeOverDraft}
      />
    </div>
  );
}
