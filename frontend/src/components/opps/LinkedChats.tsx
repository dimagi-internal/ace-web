import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getLinkedChats } from "../../api/opps";
import type { LinkedChat } from "../../api/types";

interface Props {
  slug: string;
  runId: string;
  skill: string;
}

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

  return (
    <div className="rounded bg-card p-2.5">
      <div className="text-[9px] uppercase tracking-wider text-muted-foreground">
        Linked chats · {loading ? "…" : chats.length}
      </div>
      {!loading && chats.length === 0 && (
        <div className="mt-1 text-[10px] text-muted-foreground">No prior chats yet.</div>
      )}
      {!loading && chats.length > 0 && (
        <ul className="mt-1 flex flex-col gap-0.5 text-[10px]">
          {chats.map((c) => (
            <li key={c.slug}>
              <Link
                to={`/chat/${c.slug}`}
                className="text-primary underline hover:text-primary/80"
              >
                {c.title}
              </Link>{" "}
              <span className="text-muted-foreground">· {c.owner_email}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
