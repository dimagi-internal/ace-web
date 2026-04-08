import type { Message } from "../api/types";
import { MessageItem } from "./MessageItem";

interface Props {
  messages: Message[];
  liveAssistantId: number | null;
  liveText: string;
}

export function MessageList({ messages, liveAssistantId, liveText }: Props) {
  return (
    <div className="flex flex-col px-4 py-2">
      {messages.map((m) => (
        <MessageItem
          key={m.id}
          message={m}
          isLive={m.id === liveAssistantId}
          liveText={m.id === liveAssistantId ? liveText : undefined}
        />
      ))}
    </div>
  );
}
