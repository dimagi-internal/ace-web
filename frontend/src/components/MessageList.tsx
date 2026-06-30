import { useMemo, useState } from "react";
import { ChevronsDownUp, ChevronsUpDown } from "lucide-react";

import type { Message } from "../api/types.ws";

import { Button } from "canopy-ui/ui";
import { MessageItem } from "./MessageItem";
import { ToolCallPair } from "./chat/ToolCallPair";
import { pairToolMessages } from "./chat/pairToolMessages";
import { WelcomePanel } from "./WelcomePanel";

interface Props {
  messages: Message[];
  onUseSuggestion?: (prompt: string) => void;
}

// Show the bulk expand/collapse toolbar once a session has more than this
// many tool rows. Below that, the per-row toggle is enough.
const TOOLBAR_THRESHOLD = 5;

type BulkState = "default" | "all" | "none";

export function MessageList({ messages, onUseSuggestion }: Props) {
  const rows = useMemo(() => pairToolMessages(messages), [messages]);
  const toolPairCount = useMemo(
    () => rows.filter((r) => r.kind === "tool_pair").length,
    [rows],
  );
  // ``default`` = each <details> uses its own native state (collapsed
  // initially, user can toggle individually). The bulk toggles flip
  // every row open or closed at once. Reverting to "default" hands
  // control back to per-row state.
  const [bulkState, setBulkState] = useState<BulkState>("default");

  if (messages.length === 0) {
    return <WelcomePanel onUseSuggestion={onUseSuggestion} />;
  }
  const forceToolOpen =
    bulkState === "all" ? true : bulkState === "none" ? false : undefined;

  return (
    <div className="flex flex-col">
      {toolPairCount > TOOLBAR_THRESHOLD && (
        <div className="sticky top-0 z-10 flex items-center justify-end gap-2 border-b border-border bg-background/80 px-4 py-1.5 backdrop-blur">
          <span className="text-xs text-muted-foreground">
            {toolPairCount} tool calls
          </span>
          <Button
            variant={bulkState === "all" ? "secondary" : "ghost"}
            size="xs"
            onClick={() => setBulkState(bulkState === "all" ? "default" : "all")}
            aria-pressed={bulkState === "all"}
          >
            <ChevronsUpDown className="h-3 w-3" />
            Expand all
          </Button>
          <Button
            variant={bulkState === "none" ? "secondary" : "ghost"}
            size="xs"
            onClick={() =>
              setBulkState(bulkState === "none" ? "default" : "none")
            }
            aria-pressed={bulkState === "none"}
          >
            <ChevronsDownUp className="h-3 w-3" />
            Collapse all
          </Button>
        </div>
      )}
      <div className="flex flex-col gap-2 p-4">
        {rows.map((row) => {
          if (row.kind === "tool_pair") {
            return (
              <ToolCallPair
                key={row.key}
                use={row.use}
                result={row.result}
                forceOpen={forceToolOpen}
              />
            );
          }
          return (
            <MessageItem
              key={row.key}
              message={row.message}
              forceToolOpen={forceToolOpen}
            />
          );
        })}
      </div>
    </div>
  );
}
