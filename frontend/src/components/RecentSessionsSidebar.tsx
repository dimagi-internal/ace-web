import { Pencil, Plus } from "lucide-react";
import { useState, type KeyboardEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { createSession, updateSession } from "../api/sessions";
import type { Session } from "../api/types";
import { notifySessionsUpdated, useRecentSessions } from "../hooks/useRecentSessions";
import { relativeTime } from "../lib/relativeTime";

interface Props {
  currentSlug: string | null;
}

interface OppGroup {
  oppSlug: string;
  /** First non-empty opp_display_name seen in this group; "" if none. */
  oppDisplayName: string;
  sessions: Session[];
}

/**
 * Partition sessions by opp_slug. Each opp the user has discussed becomes
 * its own group, in order of most-recently-touched (the input list is
 * already sorted by updated_at desc, so the first occurrence wins).
 * Unlinked sessions go into the trailing "" bucket; callers render that
 * one last as "Other chats". Suppressing the section header for the
 * single-bucket case is the caller's job.
 *
 * Sprint 2: also surface the first non-empty opp_display_name in each
 * group so the header can read "Crispr Malawi Pilot" instead of the slug.
 */
function groupByOpp(sessions: Session[]): OppGroup[] {
  const order: string[] = [];
  const buckets = new Map<string, Session[]>();
  const displayNames = new Map<string, string>();
  for (const s of sessions) {
    const key = s.opp_slug || "";
    if (!buckets.has(key)) {
      buckets.set(key, []);
      order.push(key);
    }
    buckets.get(key)!.push(s);
    if (key && !displayNames.get(key) && s.opp_display_name) {
      displayNames.set(key, s.opp_display_name);
    }
  }
  // Always render unlinked chats last, regardless of when they last moved.
  return order
    .filter((k) => k !== "")
    .concat(buckets.has("") ? [""] : [])
    .map((oppSlug) => ({
      oppSlug,
      oppDisplayName: displayNames.get(oppSlug) ?? "",
      sessions: buckets.get(oppSlug)!,
    }));
}

export function RecentSessionsSidebar({ currentSlug }: Props) {
  const { sessions, refresh } = useRecentSessions(10);
  const { workspaceSlug } = useParams<{ workspaceSlug?: string }>();
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

  const renderRow = (s: Session) => {
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
  };

  const groups = groupByOpp(sessions);
  // If every chat is unlinked, render the flat list with no group headers
  // so this change is invisible to users who don't yet use opp linkage.
  const showGroupHeaders =
    groups.length > 1 || (groups.length === 1 && groups[0].oppSlug !== "");

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
      <nav className="flex-1 overflow-y-auto px-2 pb-2">
        {sessions.length === 0 && (
          <div className="px-2 py-4 text-sm text-muted-foreground">No chats yet.</div>
        )}
        {!showGroupHeaders && sessions.map(renderRow)}
        {showGroupHeaders &&
          groups.map((g) => {
            const headerLabel =
              g.oppDisplayName || g.oppSlug || "Other chats";
            const encOpp = g.oppSlug ? encodeURIComponent(g.oppSlug) : "";
            const oppHref = workspaceSlug
              ? `/w/${workspaceSlug}/opps/${encOpp}`
              : `/opps/${encOpp}`;
            return (
              <div key={g.oppSlug || "__unlinked__"} className="mt-2 first:mt-0">
                <div className="flex items-center justify-between px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                  {g.oppSlug ? (
                    <Link
                      to={oppHref}
                      className="truncate hover:text-foreground"
                      title={
                        g.oppDisplayName && g.oppDisplayName !== g.oppSlug
                          ? `${g.oppSlug} — open in Workbench`
                          : `Open opp ${g.oppSlug}`
                      }
                    >
                      {headerLabel}
                    </Link>
                  ) : (
                    <span className="truncate">{headerLabel}</span>
                  )}
                </div>
                {g.sessions.map(renderRow)}
              </div>
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
