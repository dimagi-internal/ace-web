import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Archive, ArchiveRestore, MoreHorizontal, Plus, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  createSession,
  deleteSession,
  listSessions,
  updateSession,
  type ListSessionsParams,
} from "@/api/sessions";
import type { Session, SessionListPage } from "@/api/types";
import { uploadSession } from "@/api/ingest";

type StatusFilter = "active" | "archived" | "imported" | "";

const STATUS_FILTERS: { label: string; value: StatusFilter }[] = [
  { label: "Active", value: "active" },
  { label: "Archived", value: "archived" },
  { label: "Imported", value: "imported" },
  { label: "All", value: "" },
];

export default function SessionsPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<SessionListPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const [page, setPage] = useState(1);
  const [deleteTarget, setDeleteTarget] = useState<Session | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    const params: ListSessionsParams = { page, pageSize: 20 };
    if (query.trim()) params.q = query.trim();
    if (statusFilter) params.status = statusFilter;
    listSessions(params)
      .then((d) => { setData(d); setLoading(false); })
      .catch((err) => { setError(String(err?.message ?? err)); setLoading(false); });
  }, [query, statusFilter, page]);

  useEffect(() => {
    const timer = setTimeout(load, 300);
    return () => clearTimeout(timer);
  }, [load]);

  const handleNewChat = async () => {
    const s = await createSession();
    navigate(`/chat/${s.slug}`);
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const result = await uploadSession(file);
      toast.success(`Uploaded: ${result.message_count} messages`);
      load();
    } catch (err) {
      toast.error(String(err instanceof Error ? err.message : err));
    }
    e.target.value = "";
  };

  const handleArchiveToggle = async (s: Session) => {
    const newStatus = s.status === "archived" ? "active" : "archived";
    await updateSession(s.slug, { status: newStatus } as Partial<Session>);
    toast.success(newStatus === "archived" ? "Session archived" : "Session restored");
    load();
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    await deleteSession(deleteTarget.slug);
    toast.success("Session deleted");
    setDeleteTarget(null);
    load();
  };

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0;

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      <header className="flex items-center gap-4 border-b border-border px-6 py-3">
        <h1 className="text-lg font-semibold">Sessions</h1>
        {data && (
          <span className="text-sm text-muted-foreground">· {data.total} sessions</span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Input
            placeholder="Search titles…"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setPage(1); }}
            className="w-56"
          />
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept=".jsonl"
              className="hidden"
              onChange={handleUpload}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload className="mr-1.5 h-3.5 w-3.5" />
              Upload .jsonl
            </Button>
          </>
          <Button size="sm" onClick={handleNewChat}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            New chat
          </Button>
        </div>
      </header>

      <div className="flex items-center gap-1 border-b border-border px-6 py-2">
        {STATUS_FILTERS.map((f) => (
          <Button
            key={f.value}
            variant={statusFilter === f.value ? "default" : "ghost"}
            size="sm"
            className="h-7 text-xs"
            onClick={() => { setStatusFilter(f.value); setPage(1); }}
          >
            {f.label}
          </Button>
        ))}
      </div>

      <main className="flex-1 overflow-y-auto">
        {loading && (
          <div className="space-y-2 p-6">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        )}
        {error && (
          <div className="p-6 text-center">
            <p className="text-destructive">{error}</p>
            <Button variant="outline" size="sm" className="mt-2" onClick={load}>Retry</Button>
          </div>
        )}
        {!loading && !error && data && data.items.length === 0 && (
          <div className="p-12 text-center">
            {query ? (
              <p className="text-muted-foreground">No sessions match your search.</p>
            ) : statusFilter === "imported" ? (
              <>
                <p className="text-muted-foreground">
                  No imported sessions yet.
                </p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Upload a Claude CLI transcript (<code>.jsonl</code>) to import an
                  existing session.
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-4"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <Upload className="mr-1.5 h-3.5 w-3.5" />
                  Upload .jsonl
                </Button>
              </>
            ) : statusFilter === "archived" ? (
              <p className="text-muted-foreground">
                No archived sessions.
              </p>
            ) : (
              <>
                <p className="text-muted-foreground">No sessions yet.</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Start a chat with Claude — or upload an existing CLI transcript.
                </p>
                <Button size="sm" className="mt-4" onClick={handleNewChat}>
                  <Plus className="mr-1.5 h-3.5 w-3.5" />
                  Start a chat
                </Button>
              </>
            )}
          </div>
        )}
        {!loading && !error && data && data.items.length > 0 && (
          <div className="divide-y divide-border">
            {data.items.map((s) => (
              <div key={s.slug} className="group flex items-center gap-3 px-6 py-2.5 hover:bg-muted/50">
                <Link to={`/chat/${s.slug}`} className="flex min-w-0 flex-1 items-center gap-3">
                  <span className="truncate font-medium text-foreground">{s.title || "Untitled"}</span>
                  <Badge variant="outline" className="shrink-0 text-[10px]">{s.source}</Badge>
                  {s.status === "archived" && (
                    <Badge variant="secondary" className="shrink-0 text-[10px]">archived</Badge>
                  )}
                </Link>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {new Date(s.updated_at).toLocaleDateString()}
                </span>
                <DropdownMenu>
                  <DropdownMenuTrigger render={<Button variant="ghost" size="icon" className="h-7 w-7 opacity-0 group-hover:opacity-100" />}>
                    <MoreHorizontal className="h-4 w-4" />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent>
                    <DropdownMenuItem render={<Link to={`/chat/${s.slug}`} />}>
                      Open
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => handleArchiveToggle(s)}>
                      {s.status === "archived" ? (
                        <><ArchiveRestore className="mr-2 h-4 w-4" />Restore</>
                      ) : (
                        <><Archive className="mr-2 h-4 w-4" />Archive</>
                      )}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem className="text-destructive" onClick={() => setDeleteTarget(s)}>
                      <Trash2 className="mr-2 h-4 w-4" />Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            ))}
          </div>
        )}
      </main>

      {data && totalPages > 1 && (
        <footer className="flex items-center justify-between border-t border-border px-6 py-2 text-xs text-muted-foreground">
          <span>Page {data.page} of {totalPages} · {data.total} sessions</span>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" className="h-7" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>← Prev</Button>
            <Button variant="ghost" size="sm" className="h-7" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next →</Button>
          </div>
        </footer>
      )}

      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete session?</DialogTitle>
            <DialogDescription>
              This will permanently delete &ldquo;{deleteTarget?.title || "Untitled"}&rdquo; and all its messages. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button variant="destructive" onClick={handleDelete}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
