import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getSession, updateSession } from "../api/sessions";
import type { Session } from "../api/types";
import { AddTeammateButton } from "../components/AddTeammateButton";
import { InlineTitleEdit } from "../components/InlineTitleEdit";
import { RecentSessionsSidebar } from "../components/RecentSessionsSidebar";
import { SharePopover } from "../components/SharePopover";
import { ChatPanel } from "../components/opps/ChatPanel";

export function ChatPage() {
  const { slug = "" } = useParams();
  const [meta, setMeta] = useState<Session | null>(null);

  useEffect(() => {
    if (!slug) return;
    getSession(slug)
      .then((s) => setMeta(s))
      .catch(() => setMeta(null));
  }, [slug]);

  const handleTitleSave = async (newTitle: string) => {
    if (!meta) return;
    const updated = await updateSession(slug, { title: newTitle });
    setMeta({ ...meta, title: updated.title });
  };

  if (!meta) {
    return <div className="p-4 text-muted-foreground">Loading…</div>;
  }

  return (
    <div className="flex h-full bg-background text-foreground">
      <RecentSessionsSidebar currentSlug={slug} />
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border bg-background px-4 py-2">
          <InlineTitleEdit value={meta.title} onSave={handleTitleSave} />
          <div className="relative flex items-center gap-3">
            <AddTeammateButton slug={slug} />
            <SharePopover slug={slug} />
          </div>
        </header>
        <div className="flex-1 overflow-hidden">
          <ChatPanel slug={slug} />
        </div>
      </div>
    </div>
  );
}
