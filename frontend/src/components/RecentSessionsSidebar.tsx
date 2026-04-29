import { Pencil, Plus } from "lucide-react";
import { useState, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { createSession, updateSession } from "../api/sessions";
import { notifySessionsUpdated, useRecentSessions } from "../hooks/useRecentSessions";
import { relativeTime } from "../lib/relativeTime";

interface Props {
  currentSlug: string | null;
}

export function RecentSessionsSidebar({ currentSlug }: Props) {
  const { sessions, refresh } = useRecentSessions(10);
  const navigate = useNavigate();
  const [editingSlug, setEditingSlug] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");

  const handleNew = async () => {
    const s = await createSession();
    await refresh();
    navigate(`/chat/${s.slug}`);
  };

  const startRename = (slug: string, title: string) => {
    setEditingSlug(slug);
    setDraftTitle(title);
  };

  const commitRename = async () => {
    const slug = editingSlug;
    if (!slug) return;
    const next = draftTitle.trim();
    const original = sessions.find((s) => s.slug === slug)?.title ?? "";
    setEditingSlug(null);
    if (next && next !== original) {
      await updateSession(slug, { title: next });
      notifySessionsUpdated();
    }
  };

  const onRenameKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void commitRename();
    } else if (e.key === "Escape") {
      setEditingSlug(null);
    }
  };

  return (
    <aside className="flex w-64 flex-col border-r border-border bg-muted/30">
      <div className="p-3">
        <Button
          type="button"
          onClick={handleNew}
          className="w-full"
          size="sm"
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          New Chat
        </Button>
      </div>
      <nav className="flex-1 overflow-y-auto px-2">
        {sessions.length === 0 && (
          <div className="px-2 py-4 text-sm text-muted-foreground">No chats yet.</div>
        )}
        {sessions.map((s) => {
          const isActive = s.slug === currentSlug;
          const isEditing = editingSlug === s.slug;
          const rowClass = `group relative block rounded px-3 py-2 text-sm ${
            isActive
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground hover:bg-accent"
          }`;

          if (isEditing) {
            return (
              <div key={s.slug} className={rowClass}>
                <input
                  autoFocus
                  value={draftTitle}
                  onChange={(e) => setDraftTitle(e.target.value)}
                  onKeyDown={onRenameKey}
                  onBlur={commitRename}
                  className="w-full rounded border border-ring bg-background px-1.5 py-0.5 text-sm font-medium text-foreground outline-none"
                />
                <div className="mt-1 truncate text-xs text-muted-foreground">
                  {relativeTime(s.updated_at)}
                </div>
              </div>
            );
          }

          return (
            <Link key={s.slug} to={`/chat/${s.slug}`} className={rowClass}>
              <div className="flex items-center gap-1">
                <span className="flex-1 truncate font-medium">
                  {s.title || "Untitled"}
                </span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    startRename(s.slug, s.title);
                  }}
                  title="Rename"
                  aria-label="Rename chat"
                  className="shrink-0 rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:bg-background hover:text-foreground group-hover:opacity-100 focus:opacity-100"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
              </div>
              {s.preview && (
                <div className="truncate text-xs text-muted-foreground/80">
                  {s.preview}
                </div>
              )}
              <div className="truncate text-xs text-muted-foreground">
                {relativeTime(s.updated_at)}
              </div>
            </Link>
          );
        })}
      </nav>
      <Link
        to="/sessions"
        className="border-t border-border px-3 py-2 text-center text-xs text-muted-foreground hover:text-foreground"
      >
        View all sessions &rarr;
      </Link>
    </aside>
  );
}
