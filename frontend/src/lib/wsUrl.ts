// Resolve a WebSocket URL relative to the current page.
//
// Both ace-web's WS surfaces (chat sessions and opp updates) used to
// recompute this independently — useSessionSocket did it inline and
// useOppSocket cached a module-level WS_BASE. They diverged on whether
// to encode path segments. This helper accepts a path that's already
// percent-encoded by the caller; just splices it onto the right
// protocol + host + base.
//
// Usage:
//   wsUrl(`ws/sessions/${slug}/`)
//   wsUrl(`ws/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}/`)
export function wsUrl(path: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  // Trim a leading slash on the path so the join is unambiguous —
  // both `/api/...` and `api/...` callers land at the same URL.
  const trimmed = path.replace(/^\//, "");
  return `${protocol}//${window.location.host}${base}/${trimmed}`;
}
