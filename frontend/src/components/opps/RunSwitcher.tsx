import { Link, useNavigate } from "react-router-dom";

import type { RunSummary } from "../../api/types";

interface Props {
  slug: string;
  currentRunId: string;
  runs: RunSummary[];
}

export function RunSwitcher({ slug, currentRunId, runs }: Props) {
  const navigate = useNavigate();

  // Display labels: newest run is v{N}, next is v{N-1}, etc.
  // (runs is already newest-first.)
  const labeled = runs.map((r, i) => ({
    ...r,
    label: `v${runs.length - i}`,
  }));

  const currentIndex = labeled.findIndex((r) => r.run_id === currentRunId);
  const priorRun = currentIndex >= 0 ? labeled[currentIndex + 1] : null;

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-muted-foreground">run</span>
      <select
        value={currentRunId}
        onChange={(e) => {
          navigate(`/opps/${slug}/runs/${e.target.value}`);
        }}
        className="rounded border border-border bg-card px-2 py-1 text-xs text-foreground focus:border-ring focus:outline-none"
      >
        {labeled.map((r) => (
          <option key={r.run_id} value={r.run_id}>
            {r.label} · {r.run_id}
            {r.run_id === currentRunId ? " (current)" : ""}
          </option>
        ))}
      </select>
      {priorRun && (
        <Link
          to={`/opps/${slug}/compare?from=${priorRun.run_id}&to=${currentRunId}`}
          className="text-xs text-primary underline hover:text-primary/80"
        >
          compare to {priorRun.label}
        </Link>
      )}
    </div>
  );
}
