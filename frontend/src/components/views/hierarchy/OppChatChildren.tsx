import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { MessageSquare } from "lucide-react";

import { listSessions } from "@/api/sessions";
import type { Session } from "@/api/types.ws";
import { relativeTime } from "@/lib/relativeTime";

interface Props {
  oppSlug: string;
  workspaceSlug: string;
}

/**
 * Inline-loaded list of chats linked to an opp, rendered as nested
 * children under the opp card on the Hierarchy view.
 *
 * Fetches lazily on first expand to avoid an N×opps fan-out at
 * page-load time. Caches at the component level — the parent
 * unmounting on collapse drops the cache, which is fine; the typical
 * interaction is expand-and-stay.
 *
 * These are ace-web-native `Session` rows (mostly seeded by programmatic
 * ACE runs, not human chat — see apps/sessions/models.py's docstring), so
 * `listSessions` still has real data to show even after the interactive
 * chat UI's retirement. Each row links to the read-only structure/detail
 * view (`/chat/:slug/structure`) rather than `/chat/:slug`, which now just
 * redirects to canopy chat home.
 */
export function OppChatChildren({ oppSlug, workspaceSlug }: Props) {
  const [chats, setChats] = useState<Session[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listSessions({ opp: oppSlug, pageSize: 50, workspaceSlug })
      .then((p) => {
        if (!cancelled) setChats(p.items);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message ?? e));
      });
    return () => {
      cancelled = true;
    };
  }, [oppSlug]);

  if (error) {
    return (
      <div className="px-4 py-2 text-xs text-destructive">
        Couldn't load chats: {error}
      </div>
    );
  }
  if (chats === null) {
    return <div className="px-4 py-2 text-xs text-muted-foreground">Loading chats…</div>;
  }
  if (chats.length === 0) {
    return (
      <div className="px-4 py-2 text-xs text-muted-foreground">
        No chats linked to this opp yet.
      </div>
    );
  }

  return (
    <div className="border-t border-border/60 bg-muted/20">
      <header className="flex items-center gap-2 px-4 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        <MessageSquare className="h-3 w-3" />
        Chats <span className="font-normal text-muted-foreground/70">· {chats.length}</span>
      </header>
      <ul className="divide-y divide-border/40">
        {chats.map((c) => (
        <li key={c.slug} className="flex items-center gap-2 px-4 py-1.5 text-xs">
          <MessageSquare className="h-3 w-3 shrink-0 text-muted-foreground/70" />
          <Link
            to={`/w/${workspaceSlug}/chat/${c.slug}/structure`}
            className="min-w-0 flex-1 truncate text-foreground hover:text-primary hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {c.title || "Untitled"}
          </Link>
          {c.opp_step_skill && (
            <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
              {c.opp_step_skill}
            </span>
          )}
          <span className="shrink-0 text-[10px] text-muted-foreground">
            {c.message_count} {c.message_count === 1 ? "msg" : "msgs"}
          </span>
          <span className="shrink-0 text-[10px] text-muted-foreground">
            {relativeTime(c.updated_at)}
          </span>
        </li>
        ))}
      </ul>
    </div>
  );
}
