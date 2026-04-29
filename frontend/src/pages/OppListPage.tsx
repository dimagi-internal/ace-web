import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, ArrowDownUp, Plus, Trash2, X } from "lucide-react";

import { listOpps } from "../api/opps";
import type { OppCard } from "../api/types";
import { EmptyState, ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";
import { DeleteOppDialog } from "../components/opps/DeleteOppDialog";
import { NewOppDialog } from "../components/opps/NewOppDialog";
import { Button } from "@/components/ui/button";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; opps: OppCard[] };

type SortKey = "recent" | "score" | "status" | "slug";

const SORT_LABELS: Record<SortKey, string> = {
  recent: "Recent activity",
  score: "Score (high → low)",
  status: "Status",
  slug: "Slug (A → Z)",
};

const STATUS_RANK: Record<string, number> = {
  error: 0,
  failed: 1,
  blocked: 2,
  running: 3,
  complete: 4,
};

export default function OppListPage() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [filter, setFilter] = useState("");
  const [tagFilter, setTagFilter] = useState<string[]>([]);
  const [needsReviewOnly, setNeedsReviewOnly] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("recent");
  const [newDialogOpen, setNewDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<OppCard | null>(null);

  const load = useCallback(() => {
    setState({ kind: "loading" });
    listOpps(tagFilter.length > 0 ? tagFilter : undefined)
      .then((opps) => setState({ kind: "loaded", opps }))
      .catch((err) => setState({ kind: "error", message: String(err?.message ?? err) }));
  }, [tagFilter]);

  useEffect(load, [load]);

  const allOpps = state.kind === "loaded" ? state.opps : [];
  const needsReviewCount = useMemo(
    () => allOpps.filter((o) => (o.pending_gates ?? []).length > 0).length,
    [allOpps],
  );

  const visibleOpps = useMemo(() => {
    if (state.kind !== "loaded") return [];
    let out = state.opps;
    if (needsReviewOnly) {
      out = out.filter((o) => (o.pending_gates ?? []).length > 0);
    }
    const needle = filter.trim().toLowerCase();
    if (needle) {
      out = out.filter(
        (o) =>
          o.slug.toLowerCase().includes(needle) ||
          o.display_name.toLowerCase().includes(needle) ||
          o.tags.some((t) => t.toLowerCase().includes(needle)) ||
          o.labels.some((l) => l.toLowerCase().includes(needle)),
      );
    }
    return sortOpps(out, sortKey);
  }, [state, filter, sortKey, needsReviewOnly]);

  const toggleTagFilter = (tag: string) => {
    setTagFilter((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  };

  if (state.kind === "loading") return <LoadingSpinner label="Loading opportunities…" />;
  if (state.kind === "error") return <ErrorState message={state.message} onRetry={load} />;

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-border bg-card px-6 py-4">
        <h1 className="text-xl font-semibold text-foreground">Opportunities</h1>
        <span className="text-sm text-muted-foreground">{state.opps.length} total</span>

        {needsReviewCount > 0 && (
          <button
            type="button"
            aria-pressed={needsReviewOnly}
            onClick={() => setNeedsReviewOnly((v) => !v)}
            className={
              "flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition " +
              (needsReviewOnly
                ? "bg-amber-500 text-amber-950 hover:bg-amber-400"
                : "bg-amber-500/15 text-amber-300 hover:bg-amber-500/25")
            }
            title={needsReviewOnly ? "Clear filter" : "Show only opps with pending gates"}
          >
            <AlertCircle className="h-3.5 w-3.5" />
            Needs review ({needsReviewCount})
            {needsReviewOnly && <X className="h-3 w-3" />}
          </button>
        )}

        {tagFilter.length > 0 && (
          <div className="flex items-center gap-1 text-xs">
            <span className="text-muted-foreground">tag filter:</span>
            {tagFilter.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => toggleTagFilter(t)}
                className="flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-primary hover:bg-primary/20"
              >
                {t}
                <X className="h-3 w-3" />
              </button>
            ))}
            <button
              type="button"
              onClick={() => setTagFilter([])}
              className="text-muted-foreground underline hover:text-foreground"
            >
              clear
            </button>
          </div>
        )}

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <ArrowDownUp className="h-3.5 w-3.5" />
            Sort by
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              className="rounded border border-input bg-card px-2 py-1 text-xs text-foreground focus:border-ring focus:outline-none"
              aria-label="Sort opportunities"
            >
              {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
                <option key={k} value={k}>{SORT_LABELS[k]}</option>
              ))}
            </select>
          </label>
          <input
            type="text"
            placeholder="Filter by slug, name, tag…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-64 rounded border border-input bg-card px-3 py-1 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none"
          />
          <Button size="sm" onClick={() => setNewDialogOpen(true)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            New Opp
          </Button>
        </div>
      </header>
      <NewOppDialog open={newDialogOpen} onOpenChange={setNewDialogOpen} />
      {deleteTarget && (
        <DeleteOppDialog
          open={true}
          onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
          slug={deleteTarget.slug}
          displayName={deleteTarget.display_name}
          onDeleted={() => {
            setDeleteTarget(null);
            load();
          }}
        />
      )}

      {visibleOpps.length === 0 ? (
        filter || needsReviewOnly ? (
          <EmptyState
            title={
              needsReviewOnly
                ? "No opps awaiting review"
                : "No opps match your filter"
            }
            description={
              needsReviewOnly
                ? "Every opp has its pending gates resolved."
                : "Try a different search term."
            }
          />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-16 text-center">
            <div>
              <h2 className="text-lg font-semibold text-foreground">
                No opportunities yet
              </h2>
              <p className="mt-1 max-w-md text-sm text-muted-foreground">
                Create your first opp to start an ACE cycle in this workspace.
              </p>
            </div>
            <Button onClick={() => setNewDialogOpen(true)}>
              <Plus className="mr-1.5 h-4 w-4" />
              Create your first opp
            </Button>
          </div>
        )
      ) : (
        <div className="grid grid-cols-1 gap-3 p-6 md:grid-cols-2 xl:grid-cols-3">
          {visibleOpps.map((opp) => (
            <Link
              key={opp.slug}
              to={`/opps/${opp.slug}`}
              className="group rounded border border-border bg-card p-4 transition hover:border-primary"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h2 className="truncate font-semibold text-foreground group-hover:text-primary">
                    {opp.display_name || opp.slug}
                  </h2>
                  <div className="truncate text-xs text-muted-foreground">{opp.slug}</div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    type="button"
                    aria-label={`Delete ${opp.slug}`}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setDeleteTarget(opp);
                    }}
                    className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                  <StatusBadge status={opp.status} />
                </div>
              </div>

              {opp.eval_score !== null && opp.eval_score !== undefined && (
                <div className="mt-2">
                  <ScoreChip score={opp.eval_score} passed={opp.eval_passed} />
                </div>
              )}

              {(opp.pending_gates ?? []).length > 0 && (
                <div className="mt-2 flex items-center gap-1.5 text-xs text-amber-300">
                  <span className="inline-block h-2 w-2 rounded-full bg-amber-400" />
                  <span className="font-medium">Awaiting review:</span>
                  <span className="truncate font-mono text-amber-200">
                    {(opp.pending_gates ?? []).join(", ")}
                  </span>
                </div>
              )}

              {opp.current_step && (
                <div className="mt-3 text-sm text-muted-foreground">
                  <span className="text-muted-foreground">current:</span>{" "}
                  <span className="font-mono text-foreground">{opp.current_step}</span>
                  {opp.current_phase && (
                    <span className="ml-2 text-xs text-muted-foreground">
                      ({opp.current_phase})
                    </span>
                  )}
                </div>
              )}
              {(opp.tags.length > 0 || opp.labels.length > 0) && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {opp.tags.map((tag) => (
                    <button
                      key={`tag-${tag}`}
                      type="button"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        toggleTagFilter(tag);
                      }}
                      className={
                        "rounded-full px-2 py-0.5 text-xs transition " +
                        (tagFilter.includes(tag)
                          ? "bg-primary text-primary-foreground"
                          : "bg-primary/10 text-primary hover:bg-primary/20")
                      }
                      title={tagFilter.includes(tag) ? "Remove tag filter" : "Filter by this tag"}
                    >
                      {tag}
                    </button>
                  ))}
                  {opp.labels.map((label) => (
                    <span
                      key={`label-${label}`}
                      className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                    >
                      {label}
                    </span>
                  ))}
                </div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const tone = statusColor(status);
  return (
    <span className={`rounded px-2 py-0.5 text-xs ${tone}`}>
      {status}
    </span>
  );
}

function statusColor(status: string): string {
  switch (status) {
    case "running":
      return "bg-blue-900 text-blue-300";
    case "complete":
      return "bg-green-900 text-green-300";
    case "blocked":
      return "bg-amber-900 text-amber-300";
    case "failed":
      return "bg-red-900 text-red-300";
    default:
      return "bg-muted text-muted-foreground";
  }
}

function ScoreChip({ score, passed }: { score: number; passed: boolean | null }) {
  // Match ScorecardPanel.tsx's convention: plugin scores are usually 0-100,
  // some opps land 0-10 — branch on the value, never assume scale.
  const scoreLabel = score > 10 ? `${score.toFixed(0)}/100` : `${score.toFixed(1)}/10`;
  const tone =
    passed === true
      ? "bg-emerald-900/60 text-emerald-200 border-emerald-700"
      : passed === false
        ? "bg-red-900/60 text-red-200 border-red-700"
        : "bg-muted text-muted-foreground border-border";
  const glyph = passed === true ? "✓" : passed === false ? "✕" : "·";
  const label =
    passed === true ? "passed" : passed === false ? "failed" : "scored";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium ${tone}`}
      title={`opp-eval ${label}: ${scoreLabel}`}
    >
      <span aria-hidden="true">{glyph}</span>
      <span>{scoreLabel}</span>
      <span className="opacity-70">opp-eval {label}</span>
    </span>
  );
}

function sortOpps(opps: OppCard[], key: SortKey): OppCard[] {
  const out = [...opps];
  switch (key) {
    case "recent":
      out.sort((a, b) => {
        const at = a.created_at ?? "";
        const bt = b.created_at ?? "";
        if (at === bt) return a.slug.localeCompare(b.slug);
        return bt.localeCompare(at); // newest first
      });
      break;
    case "score":
      out.sort((a, b) => {
        const av = a.eval_score ?? -1;
        const bv = b.eval_score ?? -1;
        if (av === bv) return a.slug.localeCompare(b.slug);
        return bv - av;
      });
      break;
    case "status":
      out.sort((a, b) => {
        const ar = STATUS_RANK[a.status] ?? 99;
        const br = STATUS_RANK[b.status] ?? 99;
        if (ar === br) return a.slug.localeCompare(b.slug);
        return ar - br;
      });
      break;
    case "slug":
      out.sort((a, b) => a.slug.localeCompare(b.slug));
      break;
  }
  return out;
}
