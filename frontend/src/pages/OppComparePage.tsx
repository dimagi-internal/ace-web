import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { compareRuns } from "../api/opps";
import type { CompareResult } from "../api/types";
import { CompareTable } from "../components/opps/CompareTable";
import { ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; result: CompareResult };

export default function OppComparePage() {
  const { slug = "" } = useParams();
  const [searchParams] = useSearchParams();
  const fromId = searchParams.get("from") ?? "";
  const toId = searchParams.get("to") ?? "";
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    if (!fromId || !toId) {
      setState({ kind: "error", message: "Compare requires ?from=<id>&to=<id>" });
      return;
    }
    setState({ kind: "loading" });
    compareRuns(slug, fromId, toId)
      .then((result) => setState({ kind: "loaded", result }))
      .catch((err) => setState({ kind: "error", message: String(err?.message ?? err) }));
  }, [slug, fromId, toId]);

  if (state.kind === "loading") return <LoadingSpinner label="Loading comparison…" />;
  if (state.kind === "error") return <ErrorState message={state.message} />;

  return (
    <div className="flex h-full flex-col bg-zinc-950 text-zinc-100">
      <header className="flex items-center gap-4 border-b border-zinc-800 px-4 py-2 text-sm">
        <Link to={`/opps/${slug}`} className="text-zinc-500 hover:text-zinc-300">
          ← back
        </Link>
        <span className="font-semibold">{state.result.opp.display_name}</span>
        <span className="text-zinc-500">
          comparing <span className="font-mono text-zinc-300">{fromId}</span>
          <span className="mx-2">→</span>
          <span className="font-mono text-zinc-300">{toId}</span>
        </span>
      </header>
      <main className="flex-1 overflow-y-auto">
        <CompareTable fromRun={state.result.from_run} toRun={state.result.to_run} />
      </main>
    </div>
  );
}
