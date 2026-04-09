import { Link, useNavigate } from "react-router-dom";

import { createSession } from "../api/sessions";
import { useRecentSessions } from "../hooks/useRecentSessions";

interface Props {
  currentSlug: string | null;
}

export function RecentSessionsSidebar({ currentSlug }: Props) {
  const { sessions, refresh } = useRecentSessions(10);
  const navigate = useNavigate();

  const handleNew = async () => {
    const s = await createSession();
    await refresh();
    navigate(`/chat/${s.slug}`);
  };

  return (
    <aside className="flex w-64 flex-col border-r border-zinc-200 bg-zinc-50">
      <button
        type="button"
        onClick={handleNew}
        className="m-3 rounded bg-blue-600 px-3 py-2 text-white hover:bg-blue-700"
      >
        + New Chat
      </button>
      <nav className="flex-1 overflow-y-auto px-2">
        {sessions.length === 0 && (
          <div className="px-2 py-4 text-sm text-zinc-500">No chats yet.</div>
        )}
        {sessions.map((s) => {
          const isActive = s.slug === currentSlug;
          return (
            <Link
              key={s.slug}
              to={`/chat/${s.slug}`}
              className={`block rounded px-3 py-2 text-sm ${
                isActive
                  ? "bg-blue-100 text-blue-900"
                  : "text-zinc-700 hover:bg-zinc-200"
              }`}
            >
              <div className="truncate font-medium">
                {s.title || "Untitled"}
              </div>
              <div className="truncate text-xs text-zinc-500">
                {new Date(s.updated_at).toLocaleString()}
              </div>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
