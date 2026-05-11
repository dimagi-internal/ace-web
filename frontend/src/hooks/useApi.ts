import { useEffect, useState } from "react";

/**
 * Generic fetch+state hook with cancellation.
 *
 * Replaces the ~30-line ``useState + useEffect + cancelled`` triple
 * that's been copy-pasted into every "fetch X once on mount" hook
 * (useOppCostRollup, useMultiRunSummary, useOppRuns, …) and into
 * every page component (SessionsPage, SettingsPage, etc).
 *
 * Returns ``{ data, loading, error }``:
 * - ``data`` is null until the first resolve, and resets to null on
 *   subsequent dependency changes (matches the existing behavior of
 *   the hand-rolled hooks — callers render a loading shell on null).
 * - ``loading`` is true while a request is in flight.
 * - ``error`` carries the rejection reason, or null on success.
 *
 * The ``deps`` array is the trigger — the request fires whenever any
 * dep changes. The fetcher is recreated each render and is captured
 * fresh inside the effect to avoid the closure-staleness problem.
 *
 * Pass ``skip: true`` to suspend the request (e.g. waiting for an
 * upstream slug to resolve). The hook keeps ``data`` at null while
 * skipped — callers don't need a separate ``ready`` state.
 */
export interface UseApiOptions {
  /** Suspend the fetch until ready=true (e.g. pre-resolved slug). */
  skip?: boolean;
}

export interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: unknown;
}

export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: ReadonlyArray<unknown>,
  options: UseApiOptions = {},
): UseApiResult<T> {
  const { skip = false } = options;
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(!skip);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (skip) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetcher()
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err);
          setData(null);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skip, ...deps]);

  return { data, loading, error };
}
