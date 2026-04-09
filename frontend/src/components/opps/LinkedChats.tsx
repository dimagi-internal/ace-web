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
    <div className="rounded bg-zinc-900 p-2.5">
      <div className="text-[9px] uppercase tracking-wider text-zinc-500">
        Linked chats · {loading ? "…" : chats.length}
      </div>
      {!loading && chats.length === 0 && (
        <div className="mt-1 text-[10px] text-zinc-600">No prior chats yet.</div>
      )}
      {!loading && chats.length > 0 && (
        <ul className="mt-1 flex flex-col gap-0.5 text-[10px]">
          {chats.map((c) => (
            <li key={c.slug}>
              <Link
                to={`/chat/${c.slug}`}
                className="text-blue-400 underline hover:text-blue-300"
              >
                {c.title}
              </Link>{" "}
              <span className="text-zinc-600">· {c.owner_email}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
