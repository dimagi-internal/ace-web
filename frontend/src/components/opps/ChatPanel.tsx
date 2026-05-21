import { useEffect, useMemo, useState } from "react";

import { getSession } from "../../api/sessions";
import type { Session } from "../../api/types.ws";
import { useCliAuthStatus } from "../../hooks/useCliAuthStatus";
import { useSessionSocket } from "../../hooks/useSessionSocket";
import { useStickyBottom } from "../../hooks/useStickyBottom";
import { isDraftIdle, msUntilDraftIdle } from "../../lib/drafts";
import { ConnectionStatus } from "../ConnectionStatus";
import { MessageList } from "../MessageList";
import { PresenceChips } from "../PresenceChips";
import { SendBox } from "../SendBox";

interface Props {
  slug: string;
  /** Workspace context — used for workspace-scoped API calls. Sourced from the parent route. */
  workspaceSlug?: string;
}

/**
 * Reusable chat body: CLI auth banner, presence chips, message list, send box.
 *
 * This is the extracted body of ChatPage — the page adds its own chrome
 * (sidebar, title editor, share popover), but this component renders the
 * same chat surface whether it's in the dedicated chat page or embedded in
 * the Opp Workbench right-side panel.
 */
export function ChatPanel({ slug, workspaceSlug }: Props) {
  const [meta, setMeta] = useState<Session | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const socket = useSessionSocket(slug);
  const cliStatus = useCliAuthStatus();

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
    setMeta(null);
    setMetaError(null);
    getSession(slug, workspaceSlug ?? "")
      .then((s) => setMeta(s))
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err);
        setMetaError(msg || "session not found");
      });
  }, [slug]);

  const currentUserId = socket.state.current_user_id;
  const holderId = socket.state.active_draft?.last_editor ?? null;
  const holderIsPresent =
    holderId != null && socket.state.presence_user_ids.includes(holderId);

  // A turn is "in flight" from the moment draft.committed inserts the
  // assistant placeholder (status=pending) until chat.stream_complete
  // flips it to complete. Treat pending AND streaming as in-flight so
  // the send button stays locked out and the stop button is reachable
  // during the "waiting for first token" window.
  const inFlightMessage = useMemo(() => {
    return (
      socket.state.messages.find(
        (m) => m.status === "streaming" || m.status === "pending",
      ) ?? null
    );
  }, [socket.state.messages]);

  // Sticky-bottom scroll: dep changes on (a) new message arrival and
  // (b) streaming text growth on the last message. Using length-only
  // (cheap) instead of the full string so we don't re-run the effect
  // on every character that happens to be equal — the deps array does
  // shallow compare. See docs/learnings/draft-soft-lock-idle-timer.md
  // for the broader "React UIs need explicit timer ticks" pattern;
  // this is the streaming analog.
  const messages = socket.state.messages;
  const lastMessageLen =
    messages.length > 0 ? messages[messages.length - 1].plaintext.length : 0;
  const scrollDep = `${messages.length}:${lastMessageLen}`;
  const { containerRef, onScroll } = useStickyBottom(scrollDep);

  if (metaError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-1 p-4 text-center text-sm text-muted-foreground">
        <div>Chat unavailable</div>
        <div className="text-xs opacity-70">{metaError}</div>
      </div>
    );
  }

  if (!meta) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-sm text-muted-foreground">
        Loading chat…
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-border bg-background px-3 py-1.5 text-xs">
        <ConnectionStatus
          wsConnected={socket.connected}
          cliAuthenticated={cliStatus.authenticated}
        />
        <div className="ml-auto">
          <PresenceChips
            participants={socket.state.participants}
            presenceUserIds={socket.state.presence_user_ids}
            draftHolderId={holderId}
            draftHolderIdle={isDraftIdle(socket.state.active_draft)}
          />
        </div>
      </div>
      <div
        ref={containerRef}
        onScroll={onScroll}
        className="flex-1 overflow-y-auto"
      >
        <MessageList
          messages={socket.state.messages}
          onUseSuggestion={
            // Only offer suggestions when we actually own draft writes —
            // i.e. there's a live draft and we're either the holder or
            // the holder is idle. Otherwise the click silently no-ops
            // (updateDraft only sends when active_draft is non-null and
            // the user is the editor).
            socket.state.active_draft ? socket.updateDraft : undefined
          }
        />
      </div>
      <SendBox
        draft={socket.state.active_draft}
        currentUserId={currentUserId}
        holderIsPresent={holderIsPresent}
        isStreaming={inFlightMessage != null}
        streamingMessageId={inFlightMessage?.id ?? null}
        sessionSource={meta.source}
        sessionStatus={meta.status}
        cliHasBlob={cliStatus.hasBlob}
        cliAuthenticated={cliStatus.authenticated}
        onUpdate={socket.updateDraft}
        onSend={socket.sendChat}
        onStop={socket.stopChat}
        onTakeOver={socket.takeOverDraft}
      />
    </div>
  );
}
