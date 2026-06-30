import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { MessageSquare, Scale } from "lucide-react";

import {
  fetchActivityFeed,
  type ActivityEvent,
  type ActivityKind,
} from "@/api/activity";
import { Button } from "@marshellis/workbench/ui";
import { relativeTime } from "@/lib/relativeTime";

interface Props {
  /** Limit the feed to one opp; omit for workspace-wide. */
  oppSlug?: string;
}

const KIND_LABEL: Record<ActivityKind, string> = {
  chat: "Chats",
  verdict: "Evals",
};

const ALL_KINDS: ActivityKind[] = ["chat", "verdict"];

/**
 * Workspace-wide (or per-opp when ``oppSlug`` is set) activity feed.
 *
 * Two-column layout:
 *   - Left rail: kind filters (chat / verdict) and an opp filter
 *     populated from the events themselves (so the rail reflects what's
 *     actually in the feed, not the full opp catalog).
 *   - Canvas: events grouped by day, marker styled by kind.
 *
 * Re-fetches when filters change. Server-side filtering on opp_slug;
 * type filter is applied server-side too. The opp filter inside the
 * rail (when ``oppSlug`` isn't pinned by the prop) is client-side
 * because the server API doesn't yet support a multi-opp filter.
 */
export function TimelineView({ oppSlug }: Props) {
  const { workspaceSlug = "" } = useParams<{ workspaceSlug?: string }>();
  const [enabledKinds, setEnabledKinds] = useState<Set<ActivityKind>>(
    () => new Set(ALL_KINDS),
  );
  const [oppFilter, setOppFilter] = useState<string | null>(null);
  // Two independent event streams. Chats come from Postgres (fast,
  // <500ms); verdicts come from Drive aggregation (cold cache
  // 30-60s, warm cache <100ms). Issuing them in parallel and rendering
  // chats the moment they arrive makes the page usable while the slow
  // path resolves. Phase 3 originally bundled both into one request,
  // which made the page block on Drive even when the user only wanted
  // chat events.
  const [chatEvents, setChatEvents] = useState<ActivityEvent[] | null>(null);
  const [driveEvents, setDriveEvents] = useState<ActivityEvent[] | null>(null);
  const [driveLoading, setDriveLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wantChat = enabledKinds.has("chat");
  const wantDrive = enabledKinds.has("verdict");
  const driveTypesArg: ActivityKind[] = wantDrive ? ["verdict"] : [];

  const load = useCallback(() => {
    setError(null);
    setChatEvents(null);
    setDriveEvents(null);
    setDriveLoading(false);

    if (wantChat) {
      fetchActivityFeed({ workspaceSlug, opp: oppSlug, type: "chat" })
        .then((p) => setChatEvents(p.items))
        .catch((e) => setError(String((e as Error)?.message ?? e)));
    } else {
      setChatEvents([]);
    }

    if (wantDrive) {
      setDriveLoading(true);
      fetchActivityFeed({ workspaceSlug, opp: oppSlug, type: driveTypesArg })
        .then((p) => setDriveEvents(p.items))
        .catch((e) => setError(String((e as Error)?.message ?? e)))
        .finally(() => setDriveLoading(false));
    } else {
      setDriveEvents([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [oppSlug, wantChat, wantDrive, driveTypesArg.join(",")]);

  useEffect(() => {
    load();
  }, [load]);

  const events = useMemo(() => {
    if (chatEvents === null && driveEvents === null) return null;
    const merged = [...(chatEvents ?? []), ...(driveEvents ?? [])];
    merged.sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0));
    return merged;
  }, [chatEvents, driveEvents]);

  // Visible after applying the in-rail opp filter (only relevant when
  // we're not already pinned to a single opp via the oppSlug prop).
  const visibleEvents = useMemo(() => {
    if (!events) return [];
    if (!oppFilter) return events;
    return events.filter((e) => e.opp_slug === oppFilter);
  }, [events, oppFilter]);

  const oppCounts = useMemo(() => {
    if (!events) return [] as { slug: string; count: number }[];
    const m = new Map<string, number>();
    for (const e of events) {
      const s = e.opp_slug ?? "(unlinked)";
      m.set(s, (m.get(s) ?? 0) + 1);
    }
    return [...m.entries()]
      .map(([slug, count]) => ({ slug, count }))
      .sort((a, b) => b.count - a.count);
  }, [events]);

  const kindCounts = useMemo(() => {
    const m: Record<ActivityKind, number> = { chat: 0, verdict: 0 };
    for (const e of events ?? []) {
      if (e.kind in m) m[e.kind] += 1;
    }
    return m;
  }, [events]);

  if (error) {
    return (
      <div className="p-6 text-center">
        <p className="text-destructive">{error}</p>
        <Button variant="outline" size="sm" className="mt-2" onClick={load}>
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="grid h-full grid-cols-[220px_1fr] overflow-hidden">
      <aside className="overflow-y-auto border-r border-border bg-muted/20 p-3">
        <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Filter by type
        </h4>
        {ALL_KINDS.map((kind) => {
          const active = enabledKinds.has(kind);
          return (
            <button
              key={kind}
              type="button"
              onClick={() =>
                setEnabledKinds((prev) => {
                  const next = new Set(prev);
                  if (next.has(kind)) next.delete(kind);
                  else next.add(kind);
                  return next;
                })
              }
              className={
                "flex w-full items-center justify-between rounded px-2 py-1 text-left text-xs transition " +
                (active
                  ? "text-foreground"
                  : "text-muted-foreground/50 line-through")
              }
            >
              <span className="flex items-center gap-1.5">
                <KindIcon kind={kind} className="h-3.5 w-3.5" />
                {KIND_LABEL[kind]}
              </span>
              <span className="text-[10px] text-muted-foreground">
                {kindCounts[kind]}
              </span>
            </button>
          );
        })}

        {!oppSlug && oppCounts.length > 0 && (
          <>
            <h4 className="mb-2 mt-4 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Filter by opp
            </h4>
            <button
              type="button"
              onClick={() => setOppFilter(null)}
              className={
                "flex w-full items-center justify-between rounded px-2 py-1 text-left text-xs transition " +
                (oppFilter === null
                  ? "bg-primary/10 text-foreground"
                  : "text-muted-foreground hover:text-foreground")
              }
            >
              <span>All opps</span>
              <span className="text-[10px] text-muted-foreground">
                {events?.length ?? 0}
              </span>
            </button>
            {oppCounts.map((o) => (
              <button
                key={o.slug}
                type="button"
                onClick={() => setOppFilter(o.slug === oppFilter ? null : o.slug)}
                className={
                  "flex w-full items-center justify-between rounded px-2 py-1 text-left text-xs transition " +
                  (oppFilter === o.slug
                    ? "bg-primary/10 text-foreground"
                    : "text-muted-foreground hover:text-foreground")
                }
                title={o.slug}
              >
                <span className="truncate">{o.slug}</span>
                <span className="ml-2 shrink-0 text-[10px] text-muted-foreground">
                  {o.count}
                </span>
              </button>
            ))}
          </>
        )}
      </aside>

      <main className="overflow-y-auto px-6 py-5">
        {events === null ? (
          <p className="text-sm text-muted-foreground">Loading activity…</p>
        ) : (
          <>
            {driveLoading && (
              <p className="mb-3 text-xs text-muted-foreground/80">
                Loading evals… (chats already shown below)
              </p>
            )}
            {visibleEvents.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No activity matches the current filters.
              </p>
            ) : (
              <EventList events={visibleEvents} workspaceSlug={workspaceSlug} />
            )}
          </>
        )}
      </main>
    </div>
  );
}

function EventList({
  events,
  workspaceSlug,
}: {
  events: ActivityEvent[];
  workspaceSlug: string;
}) {
  const grouped = useMemo(() => groupByDay(events), [events]);
  return (
    <div>
      {grouped.map(([day, dayEvents]) => (
        <section key={day} className="mb-6">
          <h3 className="mb-2 border-b border-border pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {day}
          </h3>
          <ol>
            {dayEvents.map((e, i) => (
              <li
                key={`${e.kind}-${e.ts}-${i}`}
                className="grid grid-cols-[80px_28px_1fr] items-start gap-3 py-2"
              >
                <span className="pt-0.5 text-[11px] text-muted-foreground">
                  {formatTime(e.ts)}
                </span>
                <span className="flex h-6 w-6 items-center justify-center rounded-full border border-border bg-card">
                  <KindIcon kind={e.kind} className="h-3 w-3" />
                </span>
                <div>
                  <EventTitle event={e} workspaceSlug={workspaceSlug} />
                  <EventSubline event={e} />
                </div>
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

function EventTitle({
  event,
  workspaceSlug,
}: {
  event: ActivityEvent;
  workspaceSlug: string;
}) {
  if (event.kind === "chat" && event.session_slug) {
    return (
      <Link
        to={
          workspaceSlug
            ? `/w/${workspaceSlug}/chat/${event.session_slug}`
            : `/chat/${event.session_slug}`
        }
        className="text-sm text-foreground hover:text-primary hover:underline"
      >
        {event.title}
      </Link>
    );
  }
  if (event.opp_slug) {
    const encOpp = encodeURIComponent(event.opp_slug);
    const encStep = event.step_skill ? encodeURIComponent(event.step_skill) : "";
    return (
      <Link
        to={
          workspaceSlug
            ? `/w/${workspaceSlug}/opps/${encOpp}${encStep ? `/runs/r1/steps/${encStep}` : ""}`
            : `/opps/${encOpp}`
        }
        className="text-sm text-foreground hover:text-primary hover:underline"
      >
        {event.title}
      </Link>
    );
  }
  return <span className="text-sm text-foreground">{event.title}</span>;
}

function EventSubline({ event }: { event: ActivityEvent }) {
  const parts: string[] = [];
  if (event.opp_slug) parts.push(event.opp_slug);
  if (event.step_skill) parts.push(`step: ${event.step_skill}`);
  if (event.kind === "chat") {
    const m = event.meta as { message_count?: number; source?: string };
    if (m.message_count !== undefined) {
      parts.push(`${m.message_count} ${m.message_count === 1 ? "msg" : "msgs"}`);
    }
    if (m.source && m.source !== "web") parts.push(m.source);
  }
  parts.push(relativeTime(event.ts));
  return (
    <p className="mt-0.5 text-[11px] text-muted-foreground">
      {parts.join(" · ")}
    </p>
  );
}

function KindIcon({ kind, className }: { kind: ActivityKind; className?: string }) {
  switch (kind) {
    case "chat":
      return <MessageSquare className={(className ?? "") + " text-indigo-400"} />;
    case "verdict":
      // Color-tinted at the icon level so the marker carries the
      // pass/fail signal at a glance.
      return <Scale className={(className ?? "") + " text-purple-400"} />;
  }
}

function groupByDay(events: ActivityEvent[]): Array<[string, ActivityEvent[]]> {
  const groups = new Map<string, ActivityEvent[]>();
  for (const e of events) {
    const day = formatDay(e.ts);
    const list = groups.get(day) ?? [];
    list.push(e);
    groups.set(day, list);
  }
  return [...groups.entries()];
}

function formatDay(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Unknown";
  const today = new Date();
  const yesterday = new Date(today.getTime() - 24 * 60 * 60 * 1000);
  if (sameDay(d, today)) return "Today";
  if (sameDay(d, yesterday)) return "Yesterday";
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: today.getFullYear() === d.getFullYear() ? undefined : "numeric",
  });
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}
