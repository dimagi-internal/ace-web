import type { Message } from "../api/types";

import { MessageItem } from "./MessageItem";

interface Props {
  messages: Message[];
}

export function MessageList({ messages }: Props) {
  return (
    <div className="flex flex-col gap-4 p-4">
      {messages.map((m) => (
        <MessageItem key={m.id} message={m} />
      ))}
    </div>
  );
}
