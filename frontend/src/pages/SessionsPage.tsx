import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Archive, ArchiveRestore, MoreHorizontal, Plus, Trash2, Upload, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "canopy-ui/ui";
import { Input } from "canopy-ui/ui";
import { Badge } from "canopy-ui/ui";
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
import { Skeleton } from "canopy-ui/ui";
import {
  createSession,
  deleteSession,
  listSessions,
  updateSession,
  type ListSessionsParams,
} from "@/api/sessions";
import { listOpps } from "@/api/opps";
import type { OppCard, Session, SessionListPage } from "@/api/types.ws";
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
  const { workspaceSlug } = useParams<{ workspaceSlug?: string }>();
  const [data, setData] = useState<SessionListPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const [oppFilter, setOppFilter] = useState<string>("");
  const [opps, setOpps] = useState<OppCard[]>([]);
  const [page, setPage] = useState(1);
  const [deleteTarget, setDeleteTarget] = useState<Session | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Populate the Opp filter dropdown once on mount. Cardinality is small
  // (typically <20 opps per workspace), so loading the full list once and
  // doing client-side filtering is simpler than wiring an autocomplete.
  // Opps that no chat is linked to still appear in the dropdown — that's
  // fine; selecting one returns an empty list (server-filtered).
  useEffect(() => {
    if (!workspaceSlug) return;
    listOpps(workspaceSlug)
      .then(setOpps)
      .catch(() => setOpps([]));
  }, [workspaceSlug]);

  const oppDisplayBySlug = useMemo(() => {
    const m = new Map<string, string>();
    for (const o of opps) m.set(o.slug, o.display_name || o.slug);
    return m;
  }, [opps]);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    const params: ListSessionsParams = { page, pageSize: 20 };
    if (query.trim()) params.q = query.trim();
    if (statusFilter) params.status = statusFilter;
    if (oppFilter) params.opp = oppFilter;
    listSessions({ ...params, workspaceSlug })
      .then((d) => { setData(d); setLoading(false); })
      .catch((err) => { setError(String(err?.message ?? err)); setLoading(false); });
  }, [query, statusFilter, oppFilter, page, workspaceSlug]);

  useEffect(() => {
    const timer = setTimeout(load, 300);
    return () => clearTimeout(timer);
  }, [load]);

  const handleNewChat = async () => {
    const s = await createSession(workspaceSlug ?? "");
    navigate(workspaceSlug ? `/w/${workspaceSlug}/chat/${s.slug}` : `/chat/${s.slug}`);
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const result = await uploadSession(file, workspaceSlug);
      toast.success(`Uploaded: ${result.message_count} messages`);
      load();
    } catch (err) {
      toast.error(String(err instanceof Error ? err.message : err));
    }
    e.target.value = "";
  };

  const handleArchiveToggle = async (s: Session) => {
    const newStatus = s.status === "archived" ? "active" : "archived";
    await updateSession(s.slug, { status: newStatus } as Partial<Session>, workspaceSlug ?? "");
    toast.success(newStatus === "archived" ? "Session archived" : "Session restored");
    load();
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    await deleteSession(deleteTarget.slug, workspaceSlug ?? "");
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
            placeholder="Search titles or chat content…"
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
        <span className="mx-2 h-4 w-px bg-border" aria-hidden="true" />
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant={oppFilter ? "default" : "ghost"}
                size="sm"
                className="h-7 text-xs"
              />
            }
          >
            {oppFilter
              ? `Opp: ${oppDisplayBySlug.get(oppFilter) ?? oppFilter}`
              : "Opp"}
          </DropdownMenuTrigger>
          <DropdownMenuContent className="max-h-72 overflow-y-auto">
            <DropdownMenuItem
              onClick={() => { setOppFilter(""); setPage(1); }}
            >
              All opps
            </DropdownMenuItem>
            {opps.length > 0 && <DropdownMenuSeparator />}
            {opps.map((o) => (
              <DropdownMenuItem
                key={o.slug}
                onClick={() => { setOppFilter(o.slug); setPage(1); }}
              >
                {o.display_name || o.slug}
              </DropdownMenuItem>
            ))}
            {opps.length === 0 && (
              <DropdownMenuItem disabled>(no opps)</DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
        {oppFilter && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => { setOppFilter(""); setPage(1); }}
            title="Clear opp filter"
            aria-label="Clear opp filter"
          >
            <X className="h-3 w-3" />
          </Button>
        )}
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
              <div key={s.slug} className="group flex items-start gap-3 px-6 py-2.5 hover:bg-muted/50">
                <Link to={`/chat/${s.slug}`} className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="truncate font-medium text-foreground">{s.title || "Untitled"}</span>
                    {s.opp_slug && (() => {
                      // Prefer server-side display_name over the OppCard
                      // lookup so chats whose opp isn't in the dropdown
                      // (e.g. deleted opp, paginated-off list) still
                      // get a label. opp_display_name comes from the
                      // serializer and is "" when the OppWorkspace row
                      // is missing — fall through to the slug then.
                      const label =
                        s.opp_display_name ||
                        oppDisplayBySlug.get(s.opp_slug) ||
                        s.opp_slug;
                      // Drop the "opp:" prefix when the label is the real
                      // display name; we only need the prefix to disambiguate
                      // when we've fallen all the way through to the slug.
                      const fellThroughToSlug = label === s.opp_slug;
                      const display = fellThroughToSlug ? `opp: ${label}` : label;
                      const stepLabel =
                        s.opp_step_skill_display || s.opp_step_skill;
                      return (
                        <Badge
                          variant="outline"
                          className="shrink-0 border-primary/40 text-[10px] text-primary"
                          title={
                            stepLabel
                              ? `${label} (${s.opp_slug}) · step: ${stepLabel}`
                              : `${label} (${s.opp_slug})`
                          }
                        >
                          {display}
                        </Badge>
                      );
                    })()}
                    <Badge variant="outline" className="shrink-0 text-[10px]">{s.source}</Badge>
                    {s.status === "archived" && (
                      <Badge variant="secondary" className="shrink-0 text-[10px]">archived</Badge>
                    )}
                  </div>
                  {s.preview && (
                    <span className="truncate text-xs text-muted-foreground">{s.preview}</span>
                  )}
                </Link>
                <span className="shrink-0 pt-0.5 text-xs text-muted-foreground">
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
