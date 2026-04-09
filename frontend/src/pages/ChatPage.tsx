import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { getSession, updateSession } from "../api/sessions";
import { AddTeammateButton } from "../components/AddTeammateButton";
import { CliAuthBanner } from "../components/CliAuthBanner";
import { InlineTitleEdit } from "../components/InlineTitleEdit";
import { MessageList } from "../components/MessageList";
import { PresenceChips } from "../components/PresenceChips";
import { RecentSessionsSidebar } from "../components/RecentSessionsSidebar";
import { SendBox } from "../components/SendBox";
import { useSessionSocket } from "../hooks/useSessionSocket";
import type { Session } from "../api/types";

export function ChatPage() {
  const { slug = "" } = useParams();
  const [meta, setMeta] = useState<Session | null>(null);
  const socket = useSessionSocket(slug);

  useEffect(() => {
    if (!slug) return;
    getSession(slug).then((s) => setMeta(s));
  }, [slug]);

  // The consumer sends current_user_id in session.state, so we can
  // read it straight off the socket state.
  const currentUserId = socket.state.current_user_id;

  const holderId = socket.state.active_draft?.last_editor ?? null;
  const holderIsPresent =
    holderId != null && socket.state.presence_user_ids.includes(holderId);

  const streamingMessage = useMemo(() => {
    return socket.state.messages.find((m) => m.status === "streaming") ?? null;
  }, [socket.state.messages]);

  const handleTitleSave = async (newTitle: string) => {
    if (!meta) return;
    const updated = await updateSession(slug, { title: newTitle });
    setMeta({ ...meta, title: updated.title });
  };

  if (!meta) {
    return <div className="p-4 text-zinc-500">Loading…</div>;
  }

  return (
    <div className="flex h-screen">
      <RecentSessionsSidebar currentSlug={slug} />
      <div className="flex flex-1 flex-col">
        <CliAuthBanner />
        <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-2">
          <InlineTitleEdit value={meta.title} onSave={handleTitleSave} />
          <div className="flex items-center gap-3">
            <PresenceChips
              participants={socket.state.participants}
              presenceUserIds={socket.state.presence_user_ids}
              draftHolderId={holderId}
              draftHolderIdle={isIdle(socket.state.active_draft?.last_edit_at)}
            />
            <AddTeammateButton slug={slug} />
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">
          <MessageList messages={socket.state.messages} />
        </main>
        <SendBox
          draft={socket.state.active_draft}
          currentUserId={currentUserId}
          holderIsPresent={holderIsPresent}
          isStreaming={streamingMessage != null}
          streamingMessageId={streamingMessage?.id ?? null}
          onUpdate={socket.updateDraft}
          onSend={socket.sendChat}
          onStop={socket.stopChat}
          onTakeOver={socket.takeOverDraft}
        />
      </div>
    </div>
  );
}

function isIdle(lastEditAt: string | undefined): boolean {
  if (!lastEditAt) return true;
  return Date.now() - new Date(lastEditAt).getTime() > 2_000;
}
