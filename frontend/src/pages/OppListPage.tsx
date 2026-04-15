import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Plus } from "lucide-react";

import { listOpps } from "../api/opps";
import type { OppCard } from "../api/types";
import { EmptyState, ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";
import { NewOppDialog } from "../components/opps/NewOppDialog";
import { Button } from "@/components/ui/button";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; opps: OppCard[] };

export default function OppListPage() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [filter, setFilter] = useState("");
  const [newDialogOpen, setNewDialogOpen] = useState(false);

  const load = () => {
    setState({ kind: "loading" });
    listOpps()
      .then((opps) => setState({ kind: "loaded", opps }))
      .catch((err) => setState({ kind: "error", message: String(err?.message ?? err) }));
  };

  useEffect(load, []);

  const filtered = useMemo(() => {
    if (state.kind !== "loaded") return [];
    const needle = filter.trim().toLowerCase();
    if (!needle) return state.opps;
    return state.opps.filter(
      (o) =>
        o.slug.toLowerCase().includes(needle) ||
        o.display_name.toLowerCase().includes(needle) ||
        o.labels.some((l) => l.toLowerCase().includes(needle)),
    );
  }, [state, filter]);

  if (state.kind === "loading") return <LoadingSpinner label="Loading opportunities…" />;
  if (state.kind === "error") return <ErrorState message={state.message} onRetry={load} />;

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-4 border-b border-border bg-card px-6 py-4">
        <h1 className="text-xl font-semibold text-foreground">Opportunities</h1>
        <span className="text-sm text-muted-foreground">{state.opps.length} total</span>
        <input
          type="text"
          placeholder="Filter by slug, name, or label…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="ml-auto w-64 rounded border border-input bg-card px-3 py-1 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none"
        />
        <Button size="sm" onClick={() => setNewDialogOpen(true)}>
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          New Opp
        </Button>
      </header>
      <NewOppDialog open={newDialogOpen} onOpenChange={setNewDialogOpen} />

      {filtered.length === 0 ? (
        <EmptyState
          title={filter ? "No opps match your filter" : "No opportunities yet"}
          description={
            filter
              ? "Try a different search term."
              : "Run ACE against an opportunity and it will show up here."
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 p-6 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((opp) => (
            <Link
              key={opp.slug}
              to={`/opps/${opp.slug}`}
              className="group rounded border border-border bg-card p-4 transition hover:border-primary"
            >
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="font-semibold text-foreground group-hover:text-primary">
                    {opp.display_name || opp.slug}
                  </h2>
                  <div className="text-xs text-muted-foreground">{opp.slug}</div>
                </div>
                <StatusBadge status={opp.status} />
              </div>
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
              {opp.labels.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {opp.labels.map((label) => (
                    <span
                      key={label}
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
