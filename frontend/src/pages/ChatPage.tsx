import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getSession } from "../api/sessions";
import { sendMessage } from "../api/messages";
import { MessageList } from "../components/MessageList";
import { SendBox } from "../components/SendBox";
import { useStreamingMessage } from "../hooks/useStreamingMessage";
import type { SessionDetail } from "../api/types";

export function ChatPage() {
  const { slug = "" } = useParams();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [liveAssistantId, setLiveAssistantId] = useState<number | null>(null);
  const stream = useStreamingMessage(liveAssistantId);

  useEffect(() => {
    if (!slug) return;
    getSession(slug).then(setSession);
  }, [slug]);

  useEffect(() => {
    if (stream.phase === "complete" || stream.phase === "error") {
      getSession(slug).then((s) => {
        setSession(s);
        setLiveAssistantId(null);
      });
    }
  }, [stream.phase, slug]);

  const handleSend = async (text: string) => {
    if (!session) return;
    const result = await sendMessage(slug, text);
    const refreshed = await getSession(slug);
    setSession(refreshed);
    setLiveAssistantId(result.assistant_message_id);
  };

  if (!session) {
    return <div className="p-4 text-zinc-500">Loading…</div>;
  }

  const isStreaming = stream.phase === "streaming";

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-zinc-200 px-4 py-2">
        <h1 className="text-lg font-semibold">{session.title || "Untitled"}</h1>
      </header>
      <main className="flex-1 overflow-y-auto">
        <MessageList
          messages={session.messages}
          liveAssistantId={liveAssistantId}
          liveText={stream.text}
        />
      </main>
      <SendBox
        disabled={false}
        isStreaming={isStreaming}
        onSend={handleSend}
        onStop={stream.cancel}
      />
    </div>
  );
}
