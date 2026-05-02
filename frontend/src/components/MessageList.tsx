import type { Message } from "../api/types";

import { MessageItem } from "./MessageItem";
import { WelcomePanel } from "./WelcomePanel";

interface Props {
  messages: Message[];
  onUseSuggestion?: (prompt: string) => void;
}

export function MessageList({ messages, onUseSuggestion }: Props) {
  if (messages.length === 0) {
    return <WelcomePanel onUseSuggestion={onUseSuggestion} />;
  }
  return (
    <div className="flex flex-col gap-4 p-4">
      {messages.map((m) => (
        <MessageItem key={m.id} message={m} />
      ))}
    </div>
  );
}
