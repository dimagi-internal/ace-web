import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getLinkedChats } from "../../api/opps";
import type { LinkedChat } from "../../api/types";

interface Props {
  slug: string;
  runId: string;
  skill: string;
}

/**
 * Render sessions linked to this opp, grouped into two buckets:
 *
 *   - **Step-specific** (``kind === 'step'``): "Discuss in chat" seeds
 *     for this exact skill. Shown first, flush with the step detail.
 *   - **Opp-wide** (``kind === 'opp'``): sessions linked to the opp but
 *     not scoped to this step — typically transcripts uploaded by
 *     ``/ace:run --ace-web-url`` and the opp's working session. Shown
 *     in a subdued secondary section so they're findable without
 *     competing with the step-specific context.
 *
 * A small badge distinguishes uploaded transcripts (``source === 'upload'``)
 * from web-native sessions.
 */
export function LinkedChats({ slug, runId, skill }: Props) {
  const [chats, setChats] = useState<LinkedChat[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getLinkedChats(slug, runId, skill)
      .then(setChats)
      .catch(() => setChats([]))
      .finally(() => setLoading(false));
  }, [slug, runId, skill]);

  const stepChats = chats.filter((c) => c.kind === "step");
  const oppChats = chats.filter((c) => c.kind === "opp");

  return (
    <div className="rounded bg-card p-2.5">
      <div className="text-[9px] uppercase tracking-wider text-muted-foreground">
        Linked chats · {loading ? "…" : chats.length}
      </div>
      {!loading && chats.length === 0 && (
        <div className="mt-1 text-[10px] text-muted-foreground">No prior chats yet.</div>
      )}

      {!loading && stepChats.length > 0 && (
        <>
          <div className="mt-1.5 text-[9px] text-muted-foreground/70">
            For this step
          </div>
          <ChatList chats={stepChats} />
        </>
      )}

      {!loading && oppChats.length > 0 && (
        <>
          <div className="mt-2 text-[9px] text-muted-foreground/70">
            Opp-wide (uploads · working session · other steps)
          </div>
          <ChatList chats={oppChats} />
        </>
      )}
    </div>
  );
}

function ChatList({ chats }: { chats: LinkedChat[] }) {
  return (
    <ul className="mt-1 flex flex-col gap-1.5 text-[10px]">
      {chats.map((c) => (
        <li key={c.slug} className="flex flex-col gap-0.5">
          <div className="flex items-baseline gap-1.5">
            <Link
              to={`/chat/${c.slug}`}
              className="truncate text-primary underline hover:text-primary/80"
            >
              {c.title}
            </Link>
            <ChatBadges chat={c} />
            <span className="shrink-0 text-muted-foreground">· {c.owner_email}</span>
          </div>
          {c.preview && (
            <div className="truncate pl-1 text-muted-foreground/80" title={c.preview}>
              {c.preview}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function ChatBadges({ chat }: { chat: LinkedChat }) {
  return (
    <span className="flex shrink-0 items-center gap-1">
      {chat.source === "upload" && (
        <span
          className="rounded bg-blue-500/15 px-1 text-[8px] font-medium uppercase tracking-wider text-blue-500"
          title="Transcript uploaded via /ace:run --ace-web-url"
        >
          upload
        </span>
      )}
      {chat.kind === "opp" && chat.step_skill && chat.step_skill !== "" && (
        <span
          className="rounded bg-muted px-1 font-mono text-[8px] text-muted-foreground"
          title={`Scoped to step: ${chat.step_skill}`}
        >
          {chat.step_skill}
        </span>
      )}
    </span>
  );
}
